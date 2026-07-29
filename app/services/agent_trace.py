"""组装问答执行轨迹（各阶段步骤 + 耗时），供 admin 执行轨迹面板使用."""

from __future__ import annotations

from typing import Any


_TIMING_KEYS = (
    "route_ms",
    "sql_ms",
    "rag_ms",
    "enrich_ms",
    "retrieve_ms",
    "generate_ms",
    "ttft_ms",
    "total_ms",
    "cache_lookup_ms",
)


def _ms(timing: dict[str, Any], key: str) -> float | None:
    val = timing.get(key)
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def build_trace(
    *,
    mode: str,
    route: str | None,
    timing: dict[str, Any] | None,
    cache_hit: bool = False,
    cache_mode: str | None = None,
    cache_score: float | None = None,
    semantic_skipped: bool = False,
    degraded: bool = False,
    has_sql: bool = False,
    has_rag: bool = False,
    request_id: str | None = None,
    route_via: str | None = None,
) -> dict[str, Any]:
    timing = dict(timing or {})
    via = route_via or timing.get("route_via")
    steps: list[dict[str, Any]] = []

    cache_lookup_ms = _ms(timing, "cache_lookup_ms")
    if cache_lookup_ms is not None or cache_hit or semantic_skipped:
        detail: dict[str, Any] = {
            "result": (
                cache_mode
                if cache_hit
                else ("semantic_skipped" if semantic_skipped else "miss")
            )
        }
        if cache_hit and cache_score is not None:
            detail["score"] = cache_score
        steps.append(
            {
                "id": "cache_lookup",
                "label": "缓存查找",
                "status": "ok",
                "duration_ms": cache_lookup_ms if cache_lookup_ms is not None else 0.0,
                "detail": detail,
            }
        )

    if cache_hit:
        steps.append(
            {
                "id": "cache_hit",
                "label": f"缓存命中（{cache_mode or 'exact'}）",
                "status": "ok",
                "duration_ms": 0.0,
                "detail": {
                    "mode": cache_mode,
                    "score": cache_score,
                },
            }
        )
    else:
        route_ms = _ms(timing, "route_ms")
        if route_ms is not None or route:
            steps.append(
                {
                    "id": "route",
                    "label": "路由判定",
                    "status": "ok",
                    "duration_ms": route_ms if route_ms is not None else 0.0,
                    "detail": {"route": route, "via": via},
                }
            )

        sql_ms = _ms(timing, "sql_ms")
        rag_ms = _ms(timing, "rag_ms")
        if sql_ms is not None or has_sql or (route in {"sql", "hybrid"}):
            steps.append(
                {
                    "id": "retrieve_sql",
                    "label": "SQL 检索",
                    "status": "ok" if has_sql or sql_ms else "skipped",
                    "duration_ms": sql_ms if sql_ms is not None else 0.0,
                    "detail": {"has_sql_context": has_sql},
                }
            )
        if rag_ms is not None or has_rag or (route in {"rag", "hybrid"}):
            steps.append(
                {
                    "id": "retrieve_rag",
                    "label": "RAG 检索",
                    "status": "ok" if has_rag or rag_ms else "skipped",
                    "duration_ms": rag_ms if rag_ms is not None else 0.0,
                    "detail": {"has_rag_context": has_rag},
                }
            )

        enrich_ms = _ms(timing, "enrich_ms")
        if enrich_ms is not None or route == "hybrid":
            steps.append(
                {
                    "id": "enrich",
                    "label": "Hybrid Enrichment",
                    "status": "ok" if enrich_ms is not None else "skipped",
                    "duration_ms": enrich_ms if enrich_ms is not None else 0.0,
                    "detail": {},
                }
            )

        generate_ms = _ms(timing, "generate_ms")
        steps.append(
            {
                "id": "generate",
                "label": "答案生成",
                "status": "error" if degraded else "ok",
                "duration_ms": generate_ms if generate_ms is not None else 0.0,
                "detail": {
                    "ttft_ms": _ms(timing, "ttft_ms"),
                    "degraded": degraded,
                },
            }
        )

    if degraded and not any(s["id"] == "generate" for s in steps):
        steps.append(
            {
                "id": "degraded",
                "label": "降级",
                "status": "error",
                "duration_ms": 0.0,
                "detail": {},
            }
        )

    return {
        "request_id": request_id,
        "mode": mode,
        "route": route,
        "route_via": via,
        "cache": {
            "hit": cache_hit,
            "mode": cache_mode,
            "score": cache_score,
            "skipped_semantic": semantic_skipped,
        },
        "degraded": degraded,
        "total_ms": _ms(timing, "total_ms"),
        "ttft_ms": _ms(timing, "ttft_ms"),
        "steps": steps,
    }


def attach_trace(metadata: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    out = dict(metadata)
    out["trace"] = trace
    return out


def strip_trace_for_client(metadata: dict[str, Any] | None, *, keep: bool) -> dict[str, Any]:
    """非 admin 响应中移除 trace 与原始阶段耗时字段."""
    out = dict(metadata or {})
    if keep:
        return out
    out.pop("trace", None)
    for key in _TIMING_KEYS:
        out.pop(key, None)
    return out
