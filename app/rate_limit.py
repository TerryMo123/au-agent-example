"""问答限流：按用户 + IP 滑动窗口（优先 Redis，否则进程内）."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.auth import AuthUser
from app.config import get_settings
from app.observability import get_request_id

logger = logging.getLogger(__name__)

_memory_hits: dict[str, deque[float]] = defaultdict(deque)
_memory_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _redis_client():
    settings = get_settings()
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("限流 Redis 不可用，回退进程内计数: %s", exc)
        return None


def _allow_memory(key: str, *, limit: int, window_seconds: int = 60) -> bool:
    now = time.monotonic()
    with _memory_lock:
        q = _memory_hits[key]
        cutoff = now - window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def _allow_redis(client, key: str, *, limit: int, window_seconds: int = 60) -> bool:
    # 简单固定窗口：每分钟一个桶
    bucket = int(time.time() // window_seconds)
    redis_key = f"au:rl:{key}:{bucket}"
    pipe = client.pipeline()
    pipe.incr(redis_key)
    pipe.expire(redis_key, window_seconds + 5)
    count, _ = pipe.execute()
    return int(count) <= limit


def check_chat_rate_limit(*, request: Request, user: AuthUser) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    ip = _client_ip(request)
    user_key = f"user:{user.id}"
    ip_key = f"ip:{ip}"
    client = _redis_client()

    checks = [
        (user_key, settings.rate_limit_chat_per_minute, "user"),
        (ip_key, settings.rate_limit_ip_per_minute, "ip"),
    ]
    for key, limit, kind in checks:
        if limit <= 0:
            continue
        ok = (
            _allow_redis(client, key, limit=limit)
            if client is not None
            else _allow_memory(key, limit=limit)
        )
        if not ok:
            logger.warning(
                "rate_limit exceeded kind=%s key=%s limit=%s request_id=%s",
                kind,
                key,
                limit,
                get_request_id(),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁（{kind} 限流），请稍后再试",
                headers={"Retry-After": "60"},
            )
