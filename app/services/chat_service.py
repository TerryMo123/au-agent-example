import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.agent.graph import get_agent_graph
from app.agent.nodes.executor import (
    FALLBACK_ANSWER,
    enrich_sql_with_rag,
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
from app.config import get_settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.semantic_cache import CacheHit, get_semantic_qa_cache
from app.services.session_service import SessionService, get_session_service
from app.utils.sse import format_sse


class ChatService:
    def __init__(self, session_service: SessionService | None = None) -> None:
        self.graph = get_agent_graph()
        self.sessions = session_service or get_session_service()
        self.settings = get_settings()
        self.qa_cache = get_semantic_qa_cache()

    def _resolve_history(self, request: ChatRequest, session_id: str) -> list[dict[str, str]]:
        """优先使用数据库历史；若无则回退到请求体中的 history."""
        stored = self.sessions.load_history(
            session_id, limit=self.settings.session_history_limit
        )
        if stored:
            return stored
        return [{"role": m.role, "content": m.content} for m in request.history]

    def _build_initial_state(
        self, request: ChatRequest, *, role: str = "manager"
    ) -> tuple[str, dict[str, Any]]:
        session = self.sessions.get_or_create(session_id=request.session_id)
        session_id = session.session_id
        history = self._resolve_history(request, session_id)
        messages = to_langchain_messages(history, request.message)

        initial_state: dict[str, Any] = {
            "messages": messages,
            "question": request.message,
            "route": "",
            "route_via": "",
            "user_role": role if role in {"manager", "user"} else "manager",
            "metrics_context": "",
            "sql_result": "",
            "sql_rows": [],
            "rag_context": "",
            "sources": [],
            "answer": "",
            "visualizations": [],
        }
        return session_id, initial_state

    def _persist_turn(
        self,
        session_id: str,
        request: ChatRequest,
        answer: str,
        *,
        route: str | None,
        sources: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        self.sessions.append_turn(
            session_id,
            request.message,
            answer,
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
        answer: str,
        route: str | None,
        sources: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        self.qa_cache.store(
            question,
            answer=answer,
            route=route,
            sources=sources,
            visualizations=visualizations,
            metadata=metadata,
        )

    async def _chunk_cached_answer(self, answer: str) -> AsyncIterator[str]:
        """把缓存答案按块吐出，保持流式体验."""
        step = 24
        for i in range(0, len(answer), step):
            yield answer[i : i + step]
            await asyncio.sleep(0)

    def _build_response(self, session_id: str, result: dict[str, Any]) -> ChatResponse:
        raw_answer = result.get("answer", "抱歉，暂时无法回答该问题。")
        answer, visualizations = self._finalize_answer_and_viz(result, raw_answer)
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            route=result.get("route") or None,
            sources=result.get("sources", []),
            metadata=self._build_metadata(
                result, answer=answer, visualizations=visualizations
            ),
        )

    async def chat(self, request: ChatRequest, *, role: str = "manager") -> ChatResponse:
        session_id, initial_state = await asyncio.to_thread(
            self._build_initial_state, request, role=role
        )

        hit = await asyncio.to_thread(self.qa_cache.lookup, request.message)
        if hit and hit.answer:
            metadata = self._cache_hit_metadata(hit)
            await asyncio.to_thread(
                self._persist_turn,
                session_id,
                request,
                hit.answer,
                route=hit.route,
                sources=hit.sources,
                metadata=metadata,
            )
            return ChatResponse(
                answer=hit.answer,
                session_id=session_id,
                route=hit.route,
                sources=hit.sources,
                metadata=metadata,
            )

        result = await asyncio.to_thread(self.graph.invoke, initial_state)
        response = self._build_response(session_id, result)

        await asyncio.to_thread(
            self._persist_turn,
            session_id,
            request,
            response.answer,
            route=response.route,
            sources=response.sources,
            metadata=response.metadata,
        )
        await asyncio.to_thread(
            self._store_qa_cache,
            request.message,
            answer=response.answer,
            route=response.route,
            sources=response.sources,
            visualizations=list(response.metadata.get("visualizations") or []),
            metadata=response.metadata,
        )
        return response

    async def chat_stream(
        self, request: ChatRequest, *, role: str = "manager"
    ) -> AsyncIterator[str]:
        session_id, state = await asyncio.to_thread(
            self._build_initial_state, request, role=role
        )

        yield format_sse("status", {"stage": "routing", "session_id": session_id})

        if self.qa_cache.enabled:
            yield format_sse("status", {"stage": "cache_lookup"})
            hit = await asyncio.to_thread(self.qa_cache.lookup, request.message)
            if hit and hit.answer:
                metadata = self._cache_hit_metadata(hit)
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
                    route=hit.route,
                    sources=hit.sources,
                    metadata=metadata,
                )
                yield format_sse(
                    "done",
                    {
                        "answer": hit.answer,
                        "session_id": session_id,
                        "route": hit.route,
                        "sources": hit.sources,
                        "metadata": metadata,
                    },
                )
                return

        state = await asyncio.to_thread(route_question, state)
        route = state.get("route", "hybrid")
        route_via = state.get("route_via") or ""
        yield format_sse(
            "status",
            {"stage": "route", "route": route, "via": route_via},
        )

        if route == "hybrid":
            # 专项 SQL 与 RAG 并行；汇合后用 RAG 知识补全 NL2SQL
            yield format_sse("status", {"stage": "retrieving_sql_and_rag"})
            sql_state, rag_state = await asyncio.gather(
                asyncio.to_thread(retrieve_sql_context, state),
                asyncio.to_thread(retrieve_rag_context, state),
            )
            state = {
                **state,
                "metrics_context": sql_state.get("metrics_context", ""),
                "sql_result": sql_state.get("sql_result", ""),
                "sql_rows": sql_state.get("sql_rows", []),
                "visualizations": sql_state.get("visualizations", []),
                "rag_context": rag_state.get("rag_context", ""),
                "sources": rag_state.get("sources", []),
            }
            yield format_sse("status", {"stage": "enriching_sql_with_rag"})
            state = await asyncio.to_thread(enrich_sql_with_rag, state)
            yield format_sse("status", {"stage": "retrieved_hybrid"})
        else:
            if route == "sql":
                yield format_sse("status", {"stage": "retrieving_sql"})
                state = await asyncio.to_thread(retrieve_sql_context, state)
                yield format_sse("status", {"stage": "retrieved_sql"})

            if route == "rag":
                yield format_sse("status", {"stage": "retrieving_rag"})
                state = await asyncio.to_thread(retrieve_rag_context, state)
                yield format_sse("status", {"stage": "retrieved_rag"})

        yield format_sse("status", {"stage": "generating"})

        answer_parts: list[str] = []
        degraded = False
        try:
            async for token in stream_answer_tokens(state):
                answer_parts.append(token)
                yield format_sse("token", {"content": token})
        except Exception as exc:  # noqa: BLE001
            degraded = True
            fallback = (
                "抱歉，当前模型服务暂时不稳定，已自动重试仍未成功。"
                "请稍后再试；若问题紧急，可换个问法或联系信息技术部。"
            )
            answer_parts = [fallback]
            yield format_sse(
                "error",
                {"stage": "generating", "message": str(exc), "degraded": True},
            )
            yield format_sse("token", {"content": fallback})

        answer = "".join(answer_parts) or "抱歉，暂时无法回答该问题。"
        if answer == FALLBACK_ANSWER:
            degraded = True
            yield format_sse(
                "status",
                {"stage": "degraded", "reason": "llm_retry_exhausted"},
            )

        answer, visualizations = self._finalize_answer_and_viz(state, answer)
        state["answer"] = answer
        state["visualizations"] = visualizations
        sources = state.get("sources", [])
        metadata = self._build_metadata(
            state,
            answer=answer,
            visualizations=visualizations,
            degraded=degraded,
        )

        await asyncio.to_thread(
            self._persist_turn,
            session_id,
            request,
            answer,
            route=route,
            sources=sources,
            metadata=metadata,
        )
        await asyncio.to_thread(
            self._store_qa_cache,
            request.message,
            answer=answer,
            route=route,
            sources=sources,
            visualizations=visualizations,
            metadata=metadata,
        )

        yield format_sse(
            "done",
            {
                "answer": answer,
                "session_id": session_id,
                "route": route,
                "sources": sources,
                "metadata": metadata,
            },
        )


_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
