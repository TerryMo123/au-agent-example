"""统一问答编排：流式与非流式共用同一检索 + 生成路径."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.agent.nodes.executor import (
    FALLBACK_ANSWER,
    enrich_sql_with_rag,
    generate_answer,
    retrieve_rag_context,
    retrieve_sql_context,
    route_question,
    stream_answer_tokens,
)
from app.agent.state import to_langchain_messages
from app.agent.viz import (
    build_visualizations,
    merge_visualizations,
    parse_answer_visualizations,
)
from app.auth import AuthUser
from app.config import get_settings
from app.observability import (
    get_request_id,
    log_extra,
    observe_cache,
    observe_chat,
    set_user_role,
)
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_trace import attach_trace, build_trace, strip_trace_for_client
from app.services.semantic_cache import CacheHit, get_semantic_qa_cache
from app.services.session_service import SessionService, get_session_service
from app.utils.sse import format_sse

logger = logging.getLogger(__name__)


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class ChatService:
    def __init__(self, session_service: SessionService | None = None) -> None:
        self.sessions = session_service or get_session_service()
        self.settings = get_settings()
        self.qa_cache = get_semantic_qa_cache()

    def _resolve_history(
        self, request: ChatRequest, session_id: str, *, user_id: int
    ) -> list[dict[str, str]]:
        stored = self.sessions.load_history(
            session_id,
            user_id=user_id,
            limit=self.settings.session_history_limit,
        )
        if stored:
            return stored
        return [{"role": m.role, "content": m.content} for m in request.history]

    def _build_initial_state(
        self, request: ChatRequest, *, user: AuthUser
    ) -> tuple[str, dict[str, Any], bool]:
        session = self.sessions.get_or_create(
            user_id=user.id, session_id=request.session_id
        )
        session_id = session.session_id
        history = self._resolve_history(request, session_id, user_id=user.id)
        # 有上文则视为追问：依赖多轮上下文，不可走语义近邻缓存
        is_follow_up = bool(history)
        messages = to_langchain_messages(history, request.message)
        role = user.data_role()

        initial_state: dict[str, Any] = {
            "messages": messages,
            "question": request.message,
            "route": "",
            "route_via": "",
            "user_role": role,
            "metrics_context": "",
            "sql_result": "",
            "sql_rows": [],
            "rag_context": "",
            "sources": [],
            "answer": "",
            "visualizations": [],
        }
        return session_id, initial_state, is_follow_up

    def _persist_turn(
        self,
        session_id: str,
        request: ChatRequest,
        answer: str,
        *,
        user_id: int,
        route: str | None,
        sources: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        self.sessions.append_turn(
            session_id,
            request.message,
            answer,
            user_id=user_id,
            route=route,
            sources=sources,
            metadata=metadata,
        )

    def _finalize_answer_and_viz(
        self, state: dict[str, Any], answer: str
    ) -> tuple[str, list[dict[str, Any]]]:
        clean, from_answer = parse_answer_visualizations(answer)
        auto = list(state.get("visualizations") or [])
        if not auto and state.get("sql_rows"):
            auto = build_visualizations(
                state.get("sql_rows") or [],
                question=state.get("question") or "",
            )
        return clean or answer, merge_visualizations(auto, from_answer)

    def _build_metadata(
        self,
        result: dict[str, Any],
        *,
        answer: str,
        visualizations: list[dict[str, Any]] | None = None,
        degraded: bool | None = None,
        cache_extra: dict[str, Any] | None = None,
        timing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = {
            "has_sql_context": bool(result.get("sql_result")),
            "has_rag_context": bool(result.get("rag_context")),
            "has_metrics_context": bool(result.get("metrics_context")),
            "has_inventory_alert": "【库存预警】"
            in str(result.get("sql_result") or ""),
            "has_ad_diagnosis": "【广告诊断】"
            in str(result.get("sql_result") or ""),
            "has_return_attribution": "【退货归因】"
            in str(result.get("sql_result") or ""),
            "degraded": (
                answer == FALLBACK_ANSWER if degraded is None else degraded
            ),
            "visualizations": visualizations
            or result.get("visualizations")
            or [],
        }
        if result.get("route_via"):
            meta["route_via"] = result.get("route_via")
        if timing:
            meta.update(timing)
        if cache_extra:
            meta.update(cache_extra)
        return meta

    def _cache_hit_metadata(self, hit: CacheHit) -> dict[str, Any]:
        return {
            "cache_hit": True,
            "cache_mode": hit.mode,
            "cache_score": round(hit.score, 4),
            "cache_matched_question": hit.question,
            "visualizations": hit.visualizations,
            "degraded": False,
            **{
                k: v
                for k, v in (hit.metadata or {}).items()
                if k
                not in {
                    "cache_hit",
                    "cache_mode",
                    "cache_score",
                    "cache_matched_question",
                    "visualizations",
                    "degraded",
                }
            },
        }

    def _store_qa_cache(
        self,
        question: str,
        *,
        role: str,
        user_id: int,
        answer: str,
        route: str | None,
        sources: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
        metadata: dict[str, Any],
        is_follow_up: bool = False,
    ) -> None:
        # 追问答依赖上文，写入会污染该用户的语义索引，整条跳过
        if is_follow_up:
            return
        self.qa_cache.store(
            question,
            role=role,
            user_id=user_id,
            answer=answer,
            route=route,
            sources=sources,
            visualizations=visualizations,
            metadata=metadata,
        )

    async def _chunk_cached_answer(self, answer: str) -> AsyncIterator[str]:
        step = 24
        for i in range(0, len(answer), step):
            yield answer[i : i + step]
            await asyncio.sleep(0)

    async def _retrieve_contexts(
        self, state: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
        """统一检索编排，返回 (state, status_events, timing_ms)."""
        events: list[dict[str, Any]] = []
        timing: dict[str, float] = {}
        t_all = time.perf_counter()

        t0 = time.perf_counter()
        state = await asyncio.to_thread(route_question, state)
        timing["route_ms"] = _ms_since(t0)
        route = state.get("route", "hybrid")
        route_via = state.get("route_via") or ""
        events.append({"stage": "route", "route": route, "via": route_via})

        if route == "hybrid":
            events.append({"stage": "retrieving_sql_and_rag"})

            async def _timed_sql():
                started = time.perf_counter()
                out = await asyncio.to_thread(retrieve_sql_context, state)
                return out, _ms_since(started)

            async def _timed_rag():
                started = time.perf_counter()
                out = await asyncio.to_thread(retrieve_rag_context, state)
                return out, _ms_since(started)

            (sql_state, sql_ms), (rag_state, rag_ms) = await asyncio.gather(
                _timed_sql(), _timed_rag()
            )
            timing["sql_ms"] = sql_ms
            timing["rag_ms"] = rag_ms
            state = {
                **state,
                "metrics_context": sql_state.get("metrics_context", ""),
                "sql_result": sql_state.get("sql_result", ""),
                "sql_rows": sql_state.get("sql_rows", []),
                "visualizations": sql_state.get("visualizations", []),
                "rag_context": rag_state.get("rag_context", ""),
                "sources": rag_state.get("sources", []),
            }
            events.append({"stage": "enriching_sql_with_rag"})
            t_en = time.perf_counter()
            state = await asyncio.to_thread(enrich_sql_with_rag, state)
            timing["enrich_ms"] = _ms_since(t_en)
            events.append({"stage": "retrieved_hybrid"})
        else:
            if route == "sql":
                events.append({"stage": "retrieving_sql"})
                t_sql = time.perf_counter()
                state = await asyncio.to_thread(retrieve_sql_context, state)
                timing["sql_ms"] = _ms_since(t_sql)
                events.append({"stage": "retrieved_sql"})
            if route == "rag":
                events.append({"stage": "retrieving_rag"})
                t_rag = time.perf_counter()
                state = await asyncio.to_thread(retrieve_rag_context, state)
                timing["rag_ms"] = _ms_since(t_rag)
                events.append({"stage": "retrieved_rag"})

        timing["retrieve_ms"] = _ms_since(t_all)
        return state, events, timing

    async def _lookup_cache(
        self,
        question: str,
        *,
        role: str,
        user_id: int,
        allow_semantic: bool = True,
    ) -> tuple[CacheHit | None, dict[str, Any]]:
        """先 exact（无 embedding）；首轮才做 semantic，追问跳过语义近邻.

        返回 (hit, lookup_info)，lookup_info 含 cache_lookup_ms / semantic_skipped。
        """
        info: dict[str, Any] = {
            "cache_lookup_ms": 0.0,
            "semantic_skipped": False,
        }
        if not self.qa_cache.enabled:
            observe_cache("disabled")
            return None, info
        t0 = time.perf_counter()
        hit = await asyncio.to_thread(
            self.qa_cache.lookup_exact,
            question,
            role=role,
            user_id=user_id,
        )
        if hit:
            info["cache_lookup_ms"] = _ms_since(t0)
            observe_cache("exact")
            return hit, info
        if not allow_semantic:
            info["cache_lookup_ms"] = _ms_since(t0)
            info["semantic_skipped"] = True
            observe_cache("semantic_skipped")
            return None, info
        hit = await asyncio.to_thread(
            self.qa_cache.lookup_semantic,
            question,
            role=role,
            user_id=user_id,
        )
        info["cache_lookup_ms"] = _ms_since(t0)
        if hit:
            observe_cache("semantic")
            return hit, info
        observe_cache("miss")
        return None, info

    def _with_trace(
        self,
        metadata: dict[str, Any],
        *,
        mode: str,
        route: str | None,
        timing: dict[str, Any],
        request_id: str | None,
        cache_hit: bool = False,
        cache_mode: str | None = None,
        cache_score: float | None = None,
        semantic_skipped: bool = False,
        degraded: bool = False,
        viewer: AuthUser,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """返回 (落库用完整 metadata, 返回客户端的 metadata)."""
        full = attach_trace(
            metadata,
            build_trace(
                mode=mode,
                route=route,
                timing=timing,
                cache_hit=cache_hit,
                cache_mode=cache_mode,
                cache_score=cache_score,
                semantic_skipped=semantic_skipped,
                degraded=degraded or bool(metadata.get("degraded")),
                has_sql=bool(metadata.get("has_sql_context")),
                has_rag=bool(metadata.get("has_rag_context")),
                request_id=request_id,
                route_via=metadata.get("route_via") or timing.get("route_via"),
            ),
        )
        client = strip_trace_for_client(full, keep=viewer.is_admin)
        return full, client

    def _finish_chat_observability(
        self,
        *,
        mode: str,
        role: str,
        route: str | None,
        cache_mode: str | None,
        degraded: bool,
        timing: dict[str, Any],
        session_id: str,
    ) -> None:
        observe_chat(
            mode=mode,
            route=route,
            cache_mode=cache_mode,
            degraded=degraded,
            role=role,
            timing=timing,
        )
        logger.info(
            "chat_done mode=%s route=%s cache=%s degraded=%s session=%s timing=%s",
            mode,
            route,
            cache_mode or "miss",
            degraded,
            session_id,
            timing,
            extra=log_extra(
                route=route,
                route_via=timing.get("route_via"),
                cache_hit=bool(cache_mode),
                cache_mode=cache_mode,
                degraded=degraded,
                session_id=session_id,
            ),
        )

    async def chat(self, request: ChatRequest, *, user: AuthUser) -> ChatResponse:
        """非流式：与流式共用检索编排，再同步生成."""
        set_user_role(user.role)
        t0 = time.perf_counter()
        request_id = get_request_id()
        session_id, state, is_follow_up = await asyncio.to_thread(
            self._build_initial_state, request, user=user
        )
        role = str(state.get("user_role") or user.role)

        hit, cache_info = await self._lookup_cache(
            request.message,
            role=role,
            user_id=user.id,
            allow_semantic=not is_follow_up,
        )
        if hit and hit.answer:
            timing = {
                "total_ms": _ms_since(t0),
                "cache_lookup_ms": cache_info.get("cache_lookup_ms", 0.0),
            }
            metadata = self._cache_hit_metadata(hit)
            metadata.update(timing)
            if request_id:
                metadata["request_id"] = request_id
            store_meta, client_meta = self._with_trace(
                metadata,
                mode="sync",
                route=hit.route,
                timing=timing,
                request_id=request_id,
                cache_hit=True,
                cache_mode=hit.mode,
                cache_score=hit.score,
                degraded=False,
                viewer=user,
            )
            await asyncio.to_thread(
                self._persist_turn,
                session_id,
                request,
                hit.answer,
                user_id=user.id,
                route=hit.route,
                sources=hit.sources,
                metadata=store_meta,
            )
            self._finish_chat_observability(
                mode="sync",
                role=role,
                route=hit.route,
                cache_mode=hit.mode,
                degraded=False,
                timing=timing,
                session_id=session_id,
            )
            return ChatResponse(
                answer=hit.answer,
                session_id=session_id,
                route=hit.route,
                sources=hit.sources,
                metadata=client_meta,
            )

        state, _events, retrieve_timing = await self._retrieve_contexts(state)
        route = state.get("route") or "hybrid"

        t_gen = time.perf_counter()
        result = await asyncio.to_thread(generate_answer, state)
        generate_ms = _ms_since(t_gen)

        answer, visualizations = self._finalize_answer_and_viz(
            result, result.get("answer", FALLBACK_ANSWER)
        )
        degraded = answer == FALLBACK_ANSWER
        timing = {
            **retrieve_timing,
            "cache_lookup_ms": cache_info.get("cache_lookup_ms", 0.0),
            "generate_ms": generate_ms,
            "total_ms": _ms_since(t0),
            "route_via": result.get("route_via") or state.get("route_via"),
        }
        metadata = self._build_metadata(
            result,
            answer=answer,
            visualizations=visualizations,
            degraded=degraded,
            timing={k: v for k, v in timing.items() if k != "route_via"},
        )
        if request_id:
            metadata["request_id"] = request_id
        if timing.get("route_via"):
            metadata["route_via"] = timing["route_via"]

        store_meta, client_meta = self._with_trace(
            metadata,
            mode="sync",
            route=route,
            timing=timing,
            request_id=request_id,
            semantic_skipped=bool(cache_info.get("semantic_skipped")),
            degraded=degraded,
            viewer=user,
        )
        await asyncio.to_thread(
            self._persist_turn,
            session_id,
            request,
            answer,
            user_id=user.id,
            route=route,
            sources=result.get("sources", []),
            metadata=store_meta,
        )
        if not degraded:
            await asyncio.to_thread(
                self._store_qa_cache,
                request.message,
                role=role,
                user_id=user.id,
                answer=answer,
                route=route,
                sources=result.get("sources", []),
                visualizations=visualizations,
                metadata=store_meta,
                is_follow_up=is_follow_up,
            )

        self._finish_chat_observability(
            mode="sync",
            role=role,
            route=route,
            cache_mode=None,
            degraded=degraded,
            timing=timing,
            session_id=session_id,
        )
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            route=route,
            sources=result.get("sources", []),
            metadata=client_meta,
        )

    async def chat_stream(
        self, request: ChatRequest, *, user: AuthUser
    ) -> AsyncIterator[str]:
        """流式：与非流式共用检索编排，再 token 流式输出."""
        set_user_role(user.role)
        t0 = time.perf_counter()
        request_id = get_request_id()
        session_id, state, is_follow_up = await asyncio.to_thread(
            self._build_initial_state, request, user=user
        )
        role = str(state.get("user_role") or user.role)

        yield format_sse(
            "status",
            {
                "stage": "routing",
                "session_id": session_id,
                "request_id": request_id or None,
            },
        )

        cache_info: dict[str, Any] = {
            "cache_lookup_ms": 0.0,
            "semantic_skipped": False,
        }
        if self.qa_cache.enabled:
            yield format_sse("status", {"stage": "cache_lookup"})
            hit, cache_info = await self._lookup_cache(
                request.message,
                role=role,
                user_id=user.id,
                allow_semantic=not is_follow_up,
            )
            if hit and hit.answer:
                timing = {
                    "total_ms": _ms_since(t0),
                    "ttft_ms": _ms_since(t0),
                    "cache_lookup_ms": cache_info.get("cache_lookup_ms", 0.0),
                }
                metadata = self._cache_hit_metadata(hit)
                metadata.update(timing)
                if request_id:
                    metadata["request_id"] = request_id
                store_meta, client_meta = self._with_trace(
                    metadata,
                    mode="stream",
                    route=hit.route,
                    timing=timing,
                    request_id=request_id,
                    cache_hit=True,
                    cache_mode=hit.mode,
                    cache_score=hit.score,
                    degraded=False,
                    viewer=user,
                )
                yield format_sse(
                    "status",
                    {
                        "stage": "cache_hit",
                        "mode": hit.mode,
                        "score": round(hit.score, 4),
                    },
                )
                async for chunk in self._chunk_cached_answer(hit.answer):
                    yield format_sse("token", {"content": chunk})
                await asyncio.to_thread(
                    self._persist_turn,
                    session_id,
                    request,
                    hit.answer,
                    user_id=user.id,
                    route=hit.route,
                    sources=hit.sources,
                    metadata=store_meta,
                )
                self._finish_chat_observability(
                    mode="stream",
                    role=role,
                    route=hit.route,
                    cache_mode=hit.mode,
                    degraded=False,
                    timing=timing,
                    session_id=session_id,
                )
                yield format_sse(
                    "done",
                    {
                        "answer": hit.answer,
                        "session_id": session_id,
                        "route": hit.route,
                        "sources": hit.sources,
                        "metadata": client_meta,
                    },
                )
                return
        else:
            observe_cache("disabled")

        state, status_events, retrieve_timing = await self._retrieve_contexts(state)
        for ev in status_events:
            yield format_sse("status", ev)
        route = state.get("route", "hybrid")

        yield format_sse("status", {"stage": "generating"})

        answer_parts: list[str] = []
        degraded = False
        stream_error: str | None = None
        ttft_ms: float | None = None
        t_gen = time.perf_counter()
        try:
            async for token in stream_answer_tokens(state):
                if ttft_ms is None:
                    ttft_ms = _ms_since(t0)
                answer_parts.append(token)
                yield format_sse("token", {"content": token})
        except Exception as exc:  # noqa: BLE001
            degraded = True
            stream_error = str(exc)
            logger.warning(
                "流式生成失败: %s",
                exc,
                extra=log_extra(session_id=session_id, route=route),
            )
            yield format_sse(
                "error",
                {
                    "stage": "generating",
                    "message": stream_error,
                    "degraded": True,
                    "partial": bool(answer_parts),
                    "request_id": request_id or None,
                },
            )
            if not answer_parts:
                answer_parts = [FALLBACK_ANSWER]
                yield format_sse("token", {"content": FALLBACK_ANSWER})

        generate_ms = _ms_since(t_gen)
        answer = "".join(answer_parts) or "抱歉，暂时无法回答该问题。"
        if degraded:
            yield format_sse(
                "status",
                {
                    "stage": "degraded",
                    "reason": "llm_stream_failed" if stream_error else "llm_retry_exhausted",
                    "partial": answer != FALLBACK_ANSWER,
                },
            )
        elif answer == FALLBACK_ANSWER:
            degraded = True
            yield format_sse(
                "status",
                {"stage": "degraded", "reason": "llm_retry_exhausted"},
            )

        answer, visualizations = self._finalize_answer_and_viz(state, answer)
        state["answer"] = answer
        state["visualizations"] = visualizations
        sources = state.get("sources", [])
        timing = {
            **retrieve_timing,
            "cache_lookup_ms": cache_info.get("cache_lookup_ms", 0.0),
            "generate_ms": generate_ms,
            "ttft_ms": ttft_ms,
            "total_ms": _ms_since(t0),
            "route_via": state.get("route_via"),
        }
        metadata = self._build_metadata(
            state,
            answer=answer,
            visualizations=visualizations,
            degraded=degraded,
            timing={k: v for k, v in timing.items() if k != "route_via" and v is not None},
        )
        if request_id:
            metadata["request_id"] = request_id
        if stream_error:
            metadata["stream_error"] = stream_error
        if timing.get("route_via"):
            metadata["route_via"] = timing["route_via"]

        store_meta, client_meta = self._with_trace(
            metadata,
            mode="stream",
            route=route,
            timing=timing,
            request_id=request_id,
            semantic_skipped=bool(cache_info.get("semantic_skipped")),
            degraded=degraded,
            viewer=user,
        )
        await asyncio.to_thread(
            self._persist_turn,
            session_id,
            request,
            answer,
            user_id=user.id,
            route=route,
            sources=sources,
            metadata=store_meta,
        )
        if not degraded:
            await asyncio.to_thread(
                self._store_qa_cache,
                request.message,
                role=role,
                user_id=user.id,
                answer=answer,
                route=route,
                sources=sources,
                visualizations=visualizations,
                metadata=store_meta,
                is_follow_up=is_follow_up,
            )

        self._finish_chat_observability(
            mode="stream",
            role=role,
            route=route,
            cache_mode=None,
            degraded=degraded,
            timing=timing,
            session_id=session_id,
        )
        yield format_sse(
            "done",
            {
                "answer": answer,
                "session_id": session_id,
                "route": route,
                "sources": sources,
                "metadata": client_meta,
            },
        )


_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
