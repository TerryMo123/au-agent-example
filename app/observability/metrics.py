"""Prometheus 指标."""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "au_agent_http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
    registry=REGISTRY,
)

HTTP_LATENCY = Histogram(
    "au_agent_http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)

CHAT_REQUESTS = Counter(
    "au_agent_chat_requests_total",
    "问答请求总数",
    ["mode", "route", "cache", "degraded", "role"],
    registry=REGISTRY,
)

CHAT_STAGE_LATENCY = Histogram(
    "au_agent_chat_stage_duration_seconds",
    "问答各阶段耗时（秒）",
    ["stage", "mode"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    registry=REGISTRY,
)

CHAT_TTFT = Histogram(
    "au_agent_chat_ttft_seconds",
    "流式首 token 耗时（秒）",
    ["route", "cache"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60),
    registry=REGISTRY,
)

CACHE_LOOKUPS = Counter(
    "au_agent_cache_lookups_total",
    "语义缓存查询次数",
    ["result"],  # exact | semantic | miss | disabled
    registry=REGISTRY,
)

LLM_CALLS = Counter(
    "au_agent_llm_calls_total",
    "LLM 调用结果",
    ["operation", "result"],  # success | retry | exhausted | error
    registry=REGISTRY,
)

LLM_RETRIES = Counter(
    "au_agent_llm_retries_total",
    "LLM 重试次数",
    ["operation"],
    registry=REGISTRY,
)

DB_POOL = Gauge(
    "au_agent_db_pool",
    "SQLAlchemy 连接池状态",
    ["state"],  # size | checked_in | checked_out | overflow
    registry=REGISTRY,
)


def _norm_path(path: str) -> str:
    # 避免 session_id 等高基数
    if path.startswith("/api/v1/sessions/") and path.count("/") >= 4:
        return "/api/v1/sessions/{session_id}"
    return path


def observe_http(method: str, path: str, status: int, seconds: float) -> None:
    p = _norm_path(path)
    HTTP_REQUESTS.labels(method=method, path=p, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, path=p).observe(max(0.0, seconds))


def observe_cache(result: str) -> None:
    CACHE_LOOKUPS.labels(result=result).inc()


def observe_llm_retry(operation: str) -> None:
    LLM_RETRIES.labels(operation=operation or "llm").inc()
    LLM_CALLS.labels(operation=operation or "llm", result="retry").inc()


def observe_llm_result(operation: str, result: str) -> None:
    LLM_CALLS.labels(operation=operation or "llm", result=result).inc()


def observe_chat(
    *,
    mode: str,
    route: str | None,
    cache_mode: str | None,
    degraded: bool,
    role: str | None,
    timing: dict[str, Any] | None = None,
) -> None:
    if cache_mode in {"exact", "semantic"}:
        cache_label = cache_mode
    elif cache_mode:
        cache_label = str(cache_mode)
    else:
        cache_label = "miss"
    CHAT_REQUESTS.labels(
        mode=mode,
        route=route or "unknown",
        cache=cache_label,
        degraded="true" if degraded else "false",
        role=role or "unknown",
    ).inc()

    timing = timing or {}
    for stage in (
        "route_ms",
        "sql_ms",
        "rag_ms",
        "enrich_ms",
        "retrieve_ms",
        "generate_ms",
        "total_ms",
    ):
        val = timing.get(stage)
        if isinstance(val, (int, float)):
            CHAT_STAGE_LATENCY.labels(
                stage=stage.removesuffix("_ms"), mode=mode
            ).observe(float(val) / 1000.0)

    ttft = timing.get("ttft_ms")
    if isinstance(ttft, (int, float)):
        CHAT_TTFT.labels(
            route=route or "unknown",
            cache=cache_label,
        ).observe(float(ttft) / 1000.0)


def refresh_db_pool_gauges() -> None:
    try:
        from app.db.mysql import engine

        pool = engine.pool
        DB_POOL.labels(state="size").set(float(pool.size()))
        DB_POOL.labels(state="checked_in").set(float(pool.checkedin()))
        DB_POOL.labels(state="checked_out").set(float(pool.checkedout()))
        overflow = getattr(pool, "overflow", None)
        if callable(overflow):
            DB_POOL.labels(state="overflow").set(float(overflow()))
    except Exception:  # noqa: BLE001
        pass


def render_metrics() -> tuple[bytes, str]:
    refresh_db_pool_gauges()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
