"""健康检查：/health 存活探针；/ready 依赖就绪探针."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response, status

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _check_mysql() -> dict[str, Any]:
    from app.db.mysql import ping_mysql

    try:
        ping_mysql()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _check_redis() -> dict[str, Any]:
    settings = get_settings()
    # 语义缓存或限流任一依赖 Redis 时才强制检查；否则可跳过
    need_redis = settings.semantic_cache_enabled or settings.rate_limit_enabled
    if not need_redis:
        return {"ok": True, "skipped": True, "reason": "redis_not_required"}
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1.5,
            socket_timeout=2.0,
        )
        client.ping()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        # 限流可降级进程内；语义缓存开启时 Redis 失败仍标记 not ok
        if settings.semantic_cache_enabled:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "degraded": True, "error": str(exc)}


def _check_vector() -> dict[str, Any]:
    settings = get_settings()
    try:
        from app.vector import ping_vector_store

        ping_vector_store()
        return {"ok": True, "backend": settings.vector_backend_normalized}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "backend": settings.vector_backend_normalized,
            "error": str(exc),
        }


@router.get("/health")
async def health_check():
    """存活探针：进程能响应即可（不查外部依赖）."""
    return {"status": "ok", "service": "au-agent-backend"}


@router.get("/ready")
async def ready_check(response: Response):
    """就绪探针：MySQL + 向量库必查；Redis 在缓存启用时必查."""
    settings = get_settings()
    checks = {
        "mysql": _check_mysql(),
        "redis": _check_redis(),
        "vector": _check_vector(),
    }
    ready = all(item.get("ok") for item in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning("ready 检查未通过: %s", checks)
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "vector_stateless": settings.is_vector_stateless,
    }
