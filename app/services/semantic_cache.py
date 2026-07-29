"""问答语义缓存：Redis 精确命中 + 向量近邻复用.

设计要点:
- exact: 归一化问题哈希 → O(1) 命中，**不调用 embedding**
- semantic: 独立 embedding 索引（embidx）扫描，命中后再取完整条目
- 按 role + user_id 分片，避免跨用户/跨角色串答
- Redis 不可用时降级；按间隔自动尝试重连
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.llm import get_embeddings

logger = logging.getLogger(__name__)

_ITEM_PREFIX = "au:qa:cache:item:"
_EXACT_PREFIX = "au:qa:exact:"
_INDEX_PREFIX = "au:qa:cache:ids:"
_EMBIDX_PREFIX = "au:qa:cache:embidx:"


def normalize_question(question: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", "", q)
    q = re.sub(r"[？?！!。．.，,、；;：:\"'“”‘’（）()【】\[\]{}]", "", q)
    return q


def _normalize_role(role: str | None) -> str:
    return "manager" if role == "manager" else "user"


def _normalize_user_id(user_id: int | None) -> int:
    try:
        return max(0, int(user_id or 0))
    except (TypeError, ValueError):
        return 0


def _scope(role: str, user_id: int) -> str:
    """role + user 分片，格式如 manager:u3."""
    return f"{_normalize_role(role)}:u{_normalize_user_id(user_id)}"


def exact_key(question: str, *, role: str, user_id: int) -> str:
    digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()
    return f"{_EXACT_PREFIX}{_scope(role, user_id)}:{digest}"


def index_key(role: str, user_id: int) -> str:
    return f"{_INDEX_PREFIX}{_scope(role, user_id)}"


def emb_index_key(role: str, user_id: int) -> str:
    return f"{_EMBIDX_PREFIX}{_scope(role, user_id)}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


@dataclass
class CacheHit:
    mode: str  # exact | semantic
    score: float
    question: str
    answer: str
    route: str | None
    sources: list[dict[str, Any]]
    visualizations: list[dict[str, Any]]
    metadata: dict[str, Any]


class SemanticQACache:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._last_connect_attempt = 0.0
        self._connect(force=True)

    def _connect(self, *, force: bool = False) -> None:
        if not self.settings.semantic_cache_enabled:
            self._client = None
            return
        now = time.monotonic()
        interval = max(1.0, float(self.settings.redis_reconnect_interval_seconds))
        if (
            not force
            and self._client is None
            and (now - self._last_connect_attempt) < interval
        ):
            return
        self._last_connect_attempt = now
        try:
            import redis

            client = redis.Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=2.0,
            )
            client.ping()
            self._client = client
            logger.info("语义缓存 Redis 已连接: %s", self.settings.redis_url)
        except Exception as exc:  # noqa: BLE001
            self._client = None
            logger.warning("语义缓存 Redis 不可用，已降级: %s", exc)

    def _mark_disconnected(self, exc: BaseException) -> None:
        self._client = None
        logger.warning("语义缓存 Redis 连接失效，将择机重连: %s", exc)

    def _client_or_reconnect(self):
        if not self.settings.semantic_cache_enabled:
            return None
        if self._client is not None:
            return self._client
        self._connect(force=False)
        return self._client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.semantic_cache_enabled and self._client_or_reconnect())

    def _embed(self, text: str) -> list[float]:
        vectors = get_embeddings().embed_documents([text])
        return list(vectors[0]) if vectors else []

    def _payload_to_hit(self, payload: dict[str, Any], *, mode: str, score: float) -> CacheHit:
        return CacheHit(
            mode=mode,
            score=score,
            question=str(payload.get("question") or ""),
            answer=str(payload.get("answer") or ""),
            route=payload.get("route"),
            sources=list(payload.get("sources") or []),
            visualizations=list(payload.get("visualizations") or []),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _payload_matches_scope(
        self, payload: dict[str, Any], *, role_name: str, user_id: int
    ) -> bool:
        if _normalize_role(str(payload.get("role") or "")) != role_name:
            return False
        # 新条目带 user_id；旧 role-only 数据一律不命中，避免跨用户串答
        if "user_id" not in payload:
            return False
        return _normalize_user_id(payload.get("user_id")) == user_id

    def lookup_exact(
        self, question: str, *, role: str = "user", user_id: int = 0
    ) -> CacheHit | None:
        """仅精确命中，不调用 embedding（TTFT 友好）."""
        client = self._client_or_reconnect()
        if client is None or not (question or "").strip():
            return None
        role_name = _normalize_role(role)
        uid = _normalize_user_id(user_id)
        try:
            item_id = client.get(exact_key(question, role=role_name, user_id=uid))
            if not item_id:
                return None
            raw = client.get(f"{_ITEM_PREFIX}{item_id}")
            if not raw:
                return None
            payload = json.loads(raw)
            if not self._payload_matches_scope(
                payload, role_name=role_name, user_id=uid
            ):
                return None
            return self._payload_to_hit(payload, mode="exact", score=1.0)
        except Exception as exc:  # noqa: BLE001
            self._mark_disconnected(exc)
            return None

    def _load_emb_index(self, client, role_name: str, user_id: int) -> list[dict[str, Any]]:
        raw = client.get(emb_index_key(role_name, user_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []

    def _save_emb_index(
        self,
        client,
        role_name: str,
        user_id: int,
        entries: list[dict[str, Any]],
        *,
        ttl: int,
    ) -> None:
        max_n = max(1, int(self.settings.semantic_cache_max_entries))
        trimmed = entries[:max_n]
        client.set(
            emb_index_key(role_name, user_id),
            json.dumps(trimmed, ensure_ascii=False),
            ex=ttl,
        )

    def lookup_semantic(
        self, question: str, *, role: str = "user", user_id: int = 0
    ) -> CacheHit | None:
        """语义近邻：只扫 embidx，命中后再取完整 item."""
        client = self._client_or_reconnect()
        if client is None or not (question or "").strip():
            return None
        role_name = _normalize_role(role)
        uid = _normalize_user_id(user_id)
        try:
            query_vec = self._embed(normalize_question(question) or question)
            if not query_vec:
                return None

            entries = self._load_emb_index(client, role_name, uid)
            # 兼容：embidx 为空时回退到本用户 ids 列表逐条取 embedding
            if not entries:
                ids = client.lrange(
                    index_key(role_name, uid),
                    0,
                    self.settings.semantic_cache_max_entries - 1,
                )
                for item_id in ids:
                    raw = client.get(f"{_ITEM_PREFIX}{item_id}")
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    if not self._payload_matches_scope(
                        payload, role_name=role_name, user_id=uid
                    ):
                        continue
                    emb = payload.get("embedding") or []
                    if isinstance(emb, list) and emb:
                        entries.append({"id": item_id, "embedding": emb})

            best_id: str | None = None
            best_score = -1.0
            threshold = self.settings.semantic_cache_threshold
            for entry in entries:
                item_id = str(entry.get("id") or "")
                emb = entry.get("embedding") or []
                if not item_id or not isinstance(emb, list) or not emb:
                    continue
                score = _cosine(query_vec, [float(x) for x in emb])
                if score > best_score:
                    best_score = score
                    best_id = item_id

            if not best_id or best_score < threshold:
                return None

            raw = client.get(f"{_ITEM_PREFIX}{best_id}")
            if not raw:
                return None
            payload = json.loads(raw)
            if not self._payload_matches_scope(
                payload, role_name=role_name, user_id=uid
            ):
                return None
            return self._payload_to_hit(payload, mode="semantic", score=best_score)
        except Exception as exc:  # noqa: BLE001
            self._mark_disconnected(exc)
            return None

    def lookup(
        self, question: str, *, role: str = "user", user_id: int = 0
    ) -> CacheHit | None:
        hit = self.lookup_exact(question, role=role, user_id=user_id)
        if hit:
            return hit
        return self.lookup_semantic(question, role=role, user_id=user_id)

    def store(
        self,
        question: str,
        *,
        role: str,
        user_id: int,
        answer: str,
        route: str | None,
        sources: list[dict[str, Any]] | None,
        visualizations: list[dict[str, Any]] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        client = self._client_or_reconnect()
        if client is None:
            return
        if not (question or "").strip() or not (answer or "").strip():
            return
        meta = dict(metadata or {})
        if meta.get("degraded"):
            return
        if meta.get("cache_hit"):
            return

        role_name = _normalize_role(role)
        uid = _normalize_user_id(user_id)
        try:
            emb = self._embed(normalize_question(question) or question)
            item_id = uuid.uuid4().hex
            payload = {
                "id": item_id,
                "role": role_name,
                "user_id": uid,
                "question": question,
                "normalized": normalize_question(question),
                "answer": answer,
                "route": route,
                "sources": sources or [],
                "visualizations": visualizations or [],
                "metadata": {
                    k: v
                    for k, v in meta.items()
                    if k
                    not in {
                        "cache_hit",
                        "cache_mode",
                        "cache_score",
                        "cache_matched_question",
                    }
                },
                "embedding": emb,
                "created_at": int(time.time()),
            }
            ttl = int(self.settings.semantic_cache_ttl_seconds)
            emb_entries = self._load_emb_index(client, role_name, uid)
            emb_entries = [
                {"id": item_id, "embedding": emb},
                *[e for e in emb_entries if str(e.get("id")) != item_id],
            ]

            pipe = client.pipeline()
            pipe.set(
                f"{_ITEM_PREFIX}{item_id}",
                json.dumps(payload, ensure_ascii=False),
                ex=ttl,
            )
            pipe.set(
                exact_key(question, role=role_name, user_id=uid), item_id, ex=ttl
            )
            pipe.lpush(index_key(role_name, uid), item_id)
            pipe.ltrim(
                index_key(role_name, uid),
                0,
                self.settings.semantic_cache_max_entries - 1,
            )
            pipe.set(
                emb_index_key(role_name, uid),
                json.dumps(
                    emb_entries[: self.settings.semantic_cache_max_entries],
                    ensure_ascii=False,
                ),
                ex=ttl,
            )
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            self._mark_disconnected(exc)


_cache: SemanticQACache | None = None


def get_semantic_qa_cache() -> SemanticQACache:
    global _cache
    if _cache is None:
        _cache = SemanticQACache()
    return _cache
