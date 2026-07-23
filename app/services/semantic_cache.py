"""问答语义缓存：Redis 精确命中 + 向量近邻复用.

设计要点:
- exact: 归一化问题哈希 → O(1) 命中
- semantic: 问题 embedding 与缓存条目做余弦相似度，超过阈值则复用
- Redis 不可用或关闭时自动降级（不影响主链路）
- 仅缓存非降级、有实质内容的回答；默认 TTL，避免经营数据长期过期
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

_INDEX_KEY = "au:qa:cache:ids"
_ITEM_PREFIX = "au:qa:cache:item:"
_EXACT_PREFIX = "au:qa:exact:"


def normalize_question(question: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", "", q)
    q = re.sub(r"[？?！!。．.，,、；;：:\"'“”‘’（）()【】\[\]{}]", "", q)
    return q


def exact_key(question: str) -> str:
    digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()
    return f"{_EXACT_PREFIX}{digest}"


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
        self._connect()

    def _connect(self) -> None:
        if not self.settings.semantic_cache_enabled:
            return
        try:
            import redis

            self._client = redis.Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=2.0,
            )
            self._client.ping()
            logger.info("语义缓存 Redis 已连接: %s", self.settings.redis_url)
        except Exception as exc:  # noqa: BLE001
            self._client = None
            logger.warning("语义缓存 Redis 不可用，已降级关闭: %s", exc)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.semantic_cache_enabled and self._client is not None)

    def _embed(self, text: str) -> list[float]:
        vectors = get_embeddings().embed_documents([text])
        return list(vectors[0]) if vectors else []

    def lookup(self, question: str) -> CacheHit | None:
        if not self.enabled or not (question or "").strip():
            return None
        client = self._client
        assert client is not None

        # 1) 精确命中
        try:
            item_id = client.get(exact_key(question))
            if item_id:
                raw = client.get(f"{_ITEM_PREFIX}{item_id}")
                if raw:
                    payload = json.loads(raw)
                    return CacheHit(
                        mode="exact",
                        score=1.0,
                        question=str(payload.get("question") or ""),
                        answer=str(payload.get("answer") or ""),
                        route=payload.get("route"),
                        sources=list(payload.get("sources") or []),
                        visualizations=list(payload.get("visualizations") or []),
                        metadata=dict(payload.get("metadata") or {}),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("精确缓存查询失败: %s", exc)

        # 2) 语义近邻
        try:
            query_vec = self._embed(normalize_question(question) or question)
            if not query_vec:
                return None
            ids = client.lrange(_INDEX_KEY, 0, self.settings.semantic_cache_max_entries - 1)
            best: CacheHit | None = None
            best_score = -1.0
            threshold = self.settings.semantic_cache_threshold
            for item_id in ids:
                raw = client.get(f"{_ITEM_PREFIX}{item_id}")
                if not raw:
                    continue
                payload = json.loads(raw)
                emb = payload.get("embedding") or []
                if not isinstance(emb, list) or not emb:
                    continue
                score = _cosine(query_vec, [float(x) for x in emb])
                if score > best_score:
                    best_score = score
                    best = CacheHit(
                        mode="semantic",
                        score=score,
                        question=str(payload.get("question") or ""),
                        answer=str(payload.get("answer") or ""),
                        route=payload.get("route"),
                        sources=list(payload.get("sources") or []),
                        visualizations=list(payload.get("visualizations") or []),
                        metadata=dict(payload.get("metadata") or {}),
                    )
            if best and best_score >= threshold:
                best.score = best_score
                return best
        except Exception as exc:  # noqa: BLE001
            logger.warning("语义缓存查询失败: %s", exc)
        return None

    def store(
        self,
        question: str,
        *,
        answer: str,
        route: str | None,
        sources: list[dict[str, Any]] | None,
        visualizations: list[dict[str, Any]] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        if not self.enabled:
            return
        if not (question or "").strip() or not (answer or "").strip():
            return
        meta = dict(metadata or {})
        if meta.get("degraded"):
            return
        if meta.get("cache_hit"):
            # 命中缓存的回答不再回写，避免刷新 TTL 风暴；如需可改为 touch
            return

        client = self._client
        assert client is not None
        try:
            emb = self._embed(normalize_question(question) or question)
            item_id = uuid.uuid4().hex
            payload = {
                "id": item_id,
                "question": question,
                "normalized": normalize_question(question),
                "answer": answer,
                "route": route,
                "sources": sources or [],
                "visualizations": visualizations or [],
                "metadata": {
                    k: v
                    for k, v in meta.items()
                    if k not in {"cache_hit", "cache_mode", "cache_score", "cache_matched_question"}
                },
                "embedding": emb,
                "created_at": int(time.time()),
            }
            ttl = int(self.settings.semantic_cache_ttl_seconds)
            pipe = client.pipeline()
            pipe.set(f"{_ITEM_PREFIX}{item_id}", json.dumps(payload, ensure_ascii=False), ex=ttl)
            pipe.set(exact_key(question), item_id, ex=ttl)
            pipe.lpush(_INDEX_KEY, item_id)
            pipe.ltrim(_INDEX_KEY, 0, self.settings.semantic_cache_max_entries - 1)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("语义缓存写入失败: %s", exc)


_cache: SemanticQACache | None = None


def get_semantic_qa_cache() -> SemanticQACache:
    global _cache
    if _cache is None:
        _cache = SemanticQACache()
    return _cache
