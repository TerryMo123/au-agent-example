"""组装问答执行轨迹（细粒度行动线 + 耗时），供 admin 执行轨迹面板使用."""

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
    "parallel_wall_ms",
)

_VIA_LABEL = {
    "rule": "规则命中",
    "llm": "小模型分类",
    "fallback": "兜底降级",
}


def _ms(timing: dict[str, Any], key: str) -> float | None:
    val = timing.get(key)
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def _step(
    *,
    id: str,
    label: str,
    status: str = "ok",
    duration_ms: float | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "status": status,
        "duration_ms": float(duration_ms or 0.0),
        "detail": detail or {},
    }


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
    actions: list[dict[str, Any]] | None = None,
    stream_error: str | None = None,
    follow_up: bool = False,
) -> dict[str, Any]:
    timing = dict(timing or {})
    via = route_via or timing.get("route_via")
    steps: list[dict[str, Any]] = []

    # 1) 缓存阶段
    cache_lookup_ms = _ms(timing, "cache_lookup_ms")
    cache_result = (
        cache_mode
        if cache_hit
        else ("semantic_skipped" if semantic_skipped else "miss")
    )
    cache_detail: dict[str, Any] = {
        "result": cache_result,
        "follow_up": follow_up,
        "semantic_allowed": not semantic_skipped and not follow_up,
    }
    if cache_hit and cache_score is not None:
        cache_detail["score"] = cache_score
    if cache_lookup_ms is not None or cache_hit or semantic_skipped:
        if cache_hit:
            lookup_label = f"缓存查找命中（{cache_mode or 'exact'}）"
            lookup_status = "ok"
        elif semantic_skipped:
            lookup_label = "缓存查找：仅 exact（追问跳过 semantic）"
            lookup_status = "skipped"
        else:
            lookup_label = "缓存查找未命中（exact → semantic）"
            lookup_status = "skipped"
        steps.append(
            _step(
                id="cache_lookup",
                label=lookup_label,
                status=lookup_status,
                duration_ms=cache_lookup_ms,
                detail=cache_detail,
            )
        )
    if cache_hit:
        steps.append(
            _step(
                id="cache_hit",
                label=f"复用缓存答案（跳过路由/检索/生成）",
                status="ok",
                duration_ms=0.0,
                detail={"mode": cache_mode, "score": cache_score},
            )
        )
        return {
            "request_id": request_id,
            "mode": mode,
            "route": route,
            "route_via": via,
            "route_via_label": _VIA_LABEL.get(str(via or ""), via),
            "cache": {
                "hit": True,
                "mode": cache_mode,
                "score": cache_score,
                "skipped_semantic": semantic_skipped,
            },
            "degraded": False,
            "total_ms": _ms(timing, "total_ms"),
            "ttft_ms": _ms(timing, "ttft_ms"),
            "steps": steps,
            "action_line": [s["label"] for s in steps],
        }

    # 2) 细粒度行动线（路由规则 / Skill / RAG / NL2SQL / 生成）
    action_steps = list(actions or [])
    if action_steps:
        # 将 route_ms 摊到规则扫描 + 规则命中/小模型 上（仅作展示）
        route_ms = _ms(timing, "route_ms") or 0.0
        route_ids = {
            "route_rule_scan",
            "route_rule_hit",
            "route_llm_classify",
            "route_fallback",
        }
        route_action_count = sum(1 for a in action_steps if a.get("id") in route_ids)
        per_route = (
            round(route_ms / route_action_count, 2) if route_action_count else 0.0
        )

        sql_ms = _ms(timing, "sql_ms")
        rag_ms = _ms(timing, "rag_ms")
        enrich_ms = _ms(timing, "enrich_ms")
        generate_ms = _ms(timing, "generate_ms")
        parallel_wall_ms = _ms(timing, "parallel_wall_ms")
        has_parallel_fork = any(
            str(a.get("id") or "") == "parallel_sql_rag" for a in action_steps
        )

        for action in action_steps:
            aid = str(action.get("id") or "")
            duration = action.get("duration_ms")
            if duration is None:
                if aid in route_ids:
                    duration = per_route
                elif aid == "parallel_sql_rag":
                    duration = parallel_wall_ms
                    if duration is None and sql_ms is not None and rag_ms is not None:
                        duration = max(sql_ms, rag_ms)
                    elif duration is None:
                        duration = 0.0
                elif aid.startswith("skill_") or aid == "skill_nl2sql":
                    # 并行时墙钟已记在 fork；支路细项不再占瀑布
                    duration = 0.0
                elif aid == "retrieve_rag":
                    # 并行场景：墙钟在 parallel_sql_rag；此处仅作支路明细
                    if has_parallel_fork:
                        duration = 0.0
                    else:
                        duration = rag_ms if rag_ms is not None else 0.0
                elif aid.startswith("enrich"):
                    duration = enrich_ms if enrich_ms is not None else 0.0
                elif aid == "generate":
                    duration = generate_ms if generate_ms is not None else 0.0
                else:
                    duration = 0.0
            status = str(action.get("status") or "ok")
            if degraded and aid == "generate":
                status = "error"
            detail = dict(action.get("detail") or {})
            # 补齐并行两侧实测耗时，便于面板对照
            if aid == "parallel_sql_rag":
                if sql_ms is not None:
                    detail.setdefault("sql_branch_ms", sql_ms)
                if rag_ms is not None:
                    detail.setdefault("rag_branch_ms", rag_ms)
                if parallel_wall_ms is not None:
                    detail.setdefault("wall_ms", parallel_wall_ms)
            elif detail.get("parallel") and detail.get("branch") == "sql" and sql_ms is not None:
                detail.setdefault("branch_total_ms", sql_ms)
            elif detail.get("parallel") and detail.get("branch") == "rag" and rag_ms is not None:
                detail.setdefault("branch_total_ms", rag_ms)
            steps.append(
                _step(
                    id=aid or "action",
                    label=str(action.get("label") or aid or "步骤"),
                    status=status,
                    duration_ms=float(duration or 0.0),
                    detail=detail,
                )
            )

        # 非并行场景才追加 SQL 支路总耗时（并行已由 fork 展示两侧）
        if not has_parallel_fork and (sql_ms is not None or has_sql):
            if not any(s["id"] == "retrieve_sql_total" for s in steps):
                steps.append(
                    _step(
                        id="retrieve_sql_total",
                        label="SQL 支路总耗时",
                        status="ok" if has_sql or sql_ms else "skipped",
                        duration_ms=sql_ms,
                        detail={"has_sql_context": has_sql},
                    )
                )
    else:
        # 兼容旧数据：无 actions 时回退粗粒度
        route_ms = _ms(timing, "route_ms")
        if route_ms is not None or route:
            steps.append(
                _step(
                    id="route",
                    label=f"路由判定（{_VIA_LABEL.get(str(via or ''), via or '-')}）",
                    status="ok",
                    duration_ms=route_ms,
                    detail={"route": route, "via": via},
                )
            )
        sql_ms = _ms(timing, "sql_ms")
        rag_ms = _ms(timing, "rag_ms")
        if sql_ms is not None or has_sql or (route in {"sql", "hybrid"}):
            steps.append(
                _step(
                    id="retrieve_sql",
                    label="SQL 检索",
                    status="ok" if has_sql or sql_ms else "skipped",
                    duration_ms=sql_ms,
                    detail={"has_sql_context": has_sql},
                )
            )
        if rag_ms is not None or has_rag or (route in {"rag", "hybrid"}):
            steps.append(
                _step(
                    id="retrieve_rag",
                    label="RAG 检索",
                    status="ok" if has_rag or rag_ms else "skipped",
                    duration_ms=rag_ms,
                    detail={"has_rag_context": has_rag},
                )
            )
        enrich_ms = _ms(timing, "enrich_ms")
        if enrich_ms is not None or route == "hybrid":
            steps.append(
                _step(
                    id="enrich",
                    label="Hybrid Enrichment",
                    status="ok" if enrich_ms is not None else "skipped",
                    duration_ms=enrich_ms,
                )
            )
        generate_ms = _ms(timing, "generate_ms")
        steps.append(
            _step(
                id="generate",
                label="答案生成",
                status="error" if degraded else "ok",
                duration_ms=generate_ms,
                detail={
                    "ttft_ms": _ms(timing, "ttft_ms"),
                    "degraded": degraded,
                    "stream_error": stream_error,
                },
            )
        )

    if degraded and not any(s["id"] == "generate" for s in steps):
        steps.append(
            _step(
                id="degraded",
                label="降级结束",
                status="error",
                detail={"stream_error": stream_error},
            )
        )
    elif stream_error:
        # 已有 generate 时补错误信息
        for s in steps:
            if s["id"] == "generate":
                s["detail"] = {
                    **(s.get("detail") or {}),
                    "stream_error": stream_error,
                    "degraded": True,
                }
                s["status"] = "error"

    return {
        "request_id": request_id,
        "mode": mode,
        "route": route,
        "route_via": via,
        "route_via_label": _VIA_LABEL.get(str(via or ""), via),
        "cache": {
            "hit": False,
            "mode": cache_mode,
            "score": cache_score,
            "skipped_semantic": semantic_skipped,
        },
        "degraded": degraded,
        "total_ms": _ms(timing, "total_ms"),
        "ttft_ms": _ms(timing, "ttft_ms"),
        "steps": steps,
        "action_line": [s["label"] for s in steps],
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
