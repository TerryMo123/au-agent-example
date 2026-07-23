"""RAG / 知识检索 Skill：类目路由 + 多路召回 + 轻量重排 + 引用溯源."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document

from app.agent.skills.rag_catalog import CATEGORY_ALIASES, KNOWN_CATEGORIES
from app.vector.chroma import get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class RagHit:
    title: str
    category: str
    doc_id: str
    content: str
    score: float
    source_path: str  # vector | category_filter

    def as_source(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "doc_id": self.doc_id,
            "score": round(self.score, 4),
            "snippet": self.content[:400],
            "source_path": self.source_path,
        }


@dataclass
class RagRetrieveResult:
    question: str
    categories: list[str] = field(default_factory=list)
    hits: list[RagHit] = field(default_factory=list)

    def as_context(self) -> str:
        if not self.hits:
            return "未检索到相关内部文档。"
        header = "【内部知识检索结果】"
        if self.categories:
            header += f"（优先类目: {', '.join(self.categories)}）"
        blocks = [header]
        for idx, hit in enumerate(self.hits, start=1):
            blocks.append(
                f"[{idx}] {hit.title} ({hit.category}"
                f"{', doc_id=' + hit.doc_id if hit.doc_id else ''})\n"
                f"{hit.content}"
            )
        return "\n\n".join(blocks)

    def as_sources(self) -> list[dict[str, Any]]:
        return [h.as_source() for h in self.hits]


class RagSkill:
    """傲基内部知识 RAG Skill.

    能力:
    1. 根据问题推断文档 category（确定性关键词）
    2. 无过滤向量召回 + 类目过滤召回（多路）
    3. 按相关度 + 关键词重叠 + 类目命中轻量重排
    4. 输出可引用的 sources（title/category/doc_id/snippet）
    """

    name = "rag"
    description = "检索傲基内部政策/运营/合规等知识，支持类目过滤与引用溯源"

    def __init__(self, *, fetch_multiplier: int = 3, min_score: float = 0.18) -> None:
        self.fetch_multiplier = max(2, fetch_multiplier)
        self.min_score = min_score
        # 长别名优先
        pairs: list[tuple[str, str]] = []
        for category, aliases in CATEGORY_ALIASES.items():
            for alias in aliases:
                a = alias.strip().lower()
                if a:
                    pairs.append((a, category))
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        self._alias_pairs = pairs

    def infer_categories(self, question: str) -> list[str]:
        q = (question or "").strip().lower()
        found: list[str] = []
        seen: set[str] = set()
        for alias, category in self._alias_pairs:
            if category in seen:
                continue
            if self._alias_in_text(alias, q):
                found.append(category)
                seen.add(category)
        return found

    @staticmethod
    def _alias_in_text(alias: str, text_lower: str) -> bool:
        if not alias:
            return False
        if re.fullmatch(r"[a-z0-9_\s\-]+", alias):
            pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
            return re.search(pattern, text_lower) is not None
        return alias in text_lower

    def retrieve(
        self,
        question: str,
        *,
        top_k: int = 4,
        categories: list[str] | None = None,
    ) -> RagRetrieveResult:
        q = (question or "").strip()
        preferred = categories if categories is not None else self.infer_categories(q)
        preferred = [c for c in preferred if c in KNOWN_CATEGORIES]
        result = RagRetrieveResult(question=q, categories=preferred)

        if not q:
            return result

        store = get_vector_store()
        fetch_k = max(top_k * self.fetch_multiplier, top_k)
        candidates: list[tuple[Document, float, str]] = []

        # 路 1：全局向量召回
        try:
            for doc, score in store.similarity_search_with_relevance_scores(q, k=fetch_k):
                candidates.append((doc, float(score), "vector"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG 全局向量召回失败: %s", exc)
            try:
                for doc in store.similarity_search(q, k=fetch_k):
                    candidates.append((doc, 0.5, "vector"))
            except Exception as exc2:  # noqa: BLE001
                logger.warning("RAG 降级 similarity_search 也失败: %s", exc2)

        # 路 2：类目过滤召回（制度类更稳）
        if preferred:
            try:
                filt: dict[str, Any]
                if len(preferred) == 1:
                    filt = {"category": preferred[0]}
                else:
                    filt = {"category": {"$in": preferred}}
                for doc, score in store.similarity_search_with_relevance_scores(
                    q, k=fetch_k, filter=filt
                ):
                    candidates.append((doc, float(score), "category_filter"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG 类目过滤召回失败 categories=%s: %s", preferred, exc)

        ranked = self._rerank(q, candidates, preferred_categories=preferred)
        result.hits = [h for h in ranked if h.score >= self.min_score][:top_k]
        if result.hits:
            logger.info(
                "RAG hits=%s categories=%s titles=%s",
                len(result.hits),
                preferred,
                [h.title for h in result.hits],
            )
        return result

    def run(
        self,
        question: str,
        *,
        top_k: int = 4,
        categories: list[str] | None = None,
    ) -> RagRetrieveResult:
        return self.retrieve(question, top_k=top_k, categories=categories)

    def _rerank(
        self,
        question: str,
        candidates: list[tuple[Document, float, str]],
        *,
        preferred_categories: list[str],
    ) -> list[RagHit]:
        q_tokens = self._tokens(question)
        best: dict[str, RagHit] = {}

        for doc, base_score, path in candidates:
            meta = doc.metadata or {}
            title = str(meta.get("title") or "未知文档")
            category = str(meta.get("category") or "general")
            doc_id = str(meta.get("doc_id") or meta.get("id") or "")
            content = (doc.page_content or "").strip()
            if not content:
                continue

            key = doc_id or f"{title}::{content[:80]}"
            overlap = self._overlap_ratio(q_tokens, content + " " + title)
            cat_bonus = 0.12 if category in preferred_categories else 0.0
            # relevance_scores 通常越高越相关；再叠关键词与类目
            final = float(base_score) * 0.7 + overlap * 0.18 + cat_bonus
            hit = RagHit(
                title=title,
                category=category,
                doc_id=doc_id,
                content=content,
                score=final,
                source_path=path,
            )
            prev = best.get(key)
            if prev is None or hit.score > prev.score:
                best[key] = hit

        return sorted(best.values(), key=lambda h: h.score, reverse=True)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{2,}", text.lower())
        return set(parts)

    @staticmethod
    def _overlap_ratio(tokens: set[str], text: str) -> float:
        if not tokens:
            return 0.0
        text_l = text.lower()
        hit = sum(1 for t in tokens if t in text_l)
        return hit / len(tokens)


_rag_skill: RagSkill | None = None


def get_rag_skill() -> RagSkill:
    global _rag_skill
    if _rag_skill is None:
        _rag_skill = RagSkill()
    return _rag_skill
