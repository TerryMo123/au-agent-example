"""问题路由：规则优先，模糊时再用小模型."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import SystemMessage

from app.llm import get_router_llm
from app.llm_retry import LLMRetryExhaustedError, invoke_llm_with_retry

logger = logging.getLogger(__name__)

RouteName = Literal["sql", "rag", "hybrid"]
RouteVia = Literal["rule", "llm", "fallback"]

# 结构化数据 / 指标查询信号（长词优先，子串匹配）
_SQL_SIGNALS: tuple[str, ...] = (
    "gmv",
    "acos",
    "roas",
    "sku",
    "asin",
    "可售库存",
    "安全库存",
    "库龄",
    "在途",
    "缺货",
    "断货",
    "补货",
    "滞销",
    "退货率",
    "退货归因",
    "退货原因",
    "退货分布",
    "销量",
    "销售额",
    "订单量",
    "订单数",
    "成交额",
    "毛利",
    "转化率",
    "广告花费",
    "广告费",
    "投放花费",
    "降出价",
    "否定关键词",
    "库存预警",
    "广告诊断",
    "近7天",
    "近 7 天",
    "近30天",
    "近 30 天",
    "同比",
    "环比",
    "top",
    "排名",
    "多少钱",
    "是多少",
    "有多少",
    "库存",
    "订单",
    "采购",
    "物流时效",
    "头程",
    "海运费",
    "运费",
    "退货",
    "退款",
    "广告",
    "投放",
)

# 内部知识 / 制度 / 流程信号
_RAG_SIGNALS: tuple[str, ...] = (
    "退货政策",
    "退货规范",
    "退货处理流程",
    "退款政策",
    "内部制度",
    "运营规范",
    "作业规范",
    "合规要求",
    "质检标准",
    "包装标准",
    "产品标准",
    "审批流程",
    "折扣审批",
    "值班制度",
    "升级机制",
    "数据口径",
    "指标说明",
    "指标口径",
    "政策",
    "制度",
    "规范",
    "手册",
    "sop",
    "流程",
    "合规",
    "carb",
    "tsca",
    "ukca",
    "如何处理",
    "怎么处理",
    "如何审批",
    "怎么审批",
    "规定是什么",
    "要求是什么",
)

# 明确需要「数据 + 文档」对照
_HYBRID_SIGNALS: tuple[str, ...] = (
    "对照政策",
    "依据规范",
    "按制度",
    "结合文档",
    "参考手册",
    "对照口径",
    "既要查",
    "同时查",
)


@dataclass(frozen=True)
class RouteDecision:
    route: RouteName
    via: RouteVia
    sql_hits: tuple[str, ...] = ()
    rag_hits: tuple[str, ...] = ()
    reason: str = ""


def _normalize(question: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", "", q)
    return q


def _hits(text: str, signals: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for s in signals:
        key = re.sub(r"\s+", "", s.lower())
        if key and key in text and key not in found:
            found.append(s)
    return tuple(found)


def _norm_signal(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def _drop_dominated(hits: tuple[str, ...], dominators: tuple[str, ...]) -> tuple[str, ...]:
    """去掉被更长对侧信号包含的弱命中，如「退货」被「退货政策」覆盖."""
    if not hits or not dominators:
        return hits
    dom_norms = [_norm_signal(d) for d in dominators]
    kept: list[str] = []
    for h in hits:
        hn = _norm_signal(h)
        if any(hn != dn and hn in dn for dn in dom_norms):
            continue
        kept.append(h)
    return tuple(kept)


def rule_route(question: str) -> RouteDecision | None:
    """确定性规则路由；无法判断时返回 None，交给小模型."""
    q = _normalize(question)
    if not q:
        return RouteDecision(
            route="hybrid",
            via="rule",
            reason="empty_question",
        )

    hybrid_hits = _hits(q, _HYBRID_SIGNALS)
    sql_hits = _hits(q, _SQL_SIGNALS)
    rag_hits = _hits(q, _RAG_SIGNALS)
    # 互为子串的弱词不重复计分，避免「退货政策」→ hybrid
    sql_hits = _drop_dominated(sql_hits, rag_hits)
    rag_hits = _drop_dominated(rag_hits, sql_hits)

    if hybrid_hits:
        return RouteDecision(
            route="hybrid",
            via="rule",
            sql_hits=sql_hits,
            rag_hits=rag_hits,
            reason=f"hybrid_signal:{hybrid_hits[0]}",
        )

    has_sql = bool(sql_hits)
    has_rag = bool(rag_hits)

    if has_sql and has_rag:
        return RouteDecision(
            route="hybrid",
            via="rule",
            sql_hits=sql_hits,
            rag_hits=rag_hits,
            reason="sql_and_rag",
        )
    if has_sql:
        return RouteDecision(
            route="sql",
            via="rule",
            sql_hits=sql_hits,
            rag_hits=(),
            reason=f"sql:{sql_hits[0]}",
        )
    if has_rag:
        return RouteDecision(
            route="rag",
            via="rule",
            sql_hits=(),
            rag_hits=rag_hits,
            reason=f"rag:{rag_hits[0]}",
        )
    return None


def _parse_route_json(content: str) -> RouteName | None:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    route = data.get("route")
    if route in {"sql", "rag", "hybrid"}:
        return route  # type: ignore[return-value]
    return None


def llm_route(question: str) -> RouteDecision:
    """小模型兜底路由."""
    llm = get_router_llm()
    prompt = f"""分析用户问题，判断最适合的数据来源。
只返回 JSON: {{"route": "sql" | "rag" | "hybrid"}}

规则:
- 涉及销量、库存、SKU、订单、金额、GMV、退货、物流、广告、ACOS、采购 -> sql
- 涉及政策、流程、规范、手册、内部制度 -> rag
- 同时需要业务数据和内部文档 -> hybrid

用户问题: {question}
"""
    try:
        response = invoke_llm_with_retry(
            lambda: llm.invoke([SystemMessage(content=prompt)]),
            operation="route_question",
        )
        content = getattr(response, "content", response)
        if not isinstance(content, str):
            content = str(content)
        route = _parse_route_json(content)
        if route:
            return RouteDecision(route=route, via="llm", reason="llm_ok")
        logger.warning("路由小模型返回无法解析，降级 hybrid: %s", content[:200])
    except LLMRetryExhaustedError as exc:
        logger.warning("路由小模型重试耗尽，降级 hybrid: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("路由小模型失败，降级 hybrid: %s", exc)
    return RouteDecision(route="hybrid", via="fallback", reason="llm_failed")


def decide_route(question: str) -> RouteDecision:
    """规则优先；未命中再走小模型."""
    ruled = rule_route(question)
    if ruled is not None:
        logger.info(
            "路由命中规则 route=%s reason=%s sql=%s rag=%s",
            ruled.route,
            ruled.reason,
            ruled.sql_hits[:5],
            ruled.rag_hits[:5],
        )
        return ruled
    decision = llm_route(question)
    logger.info(
        "路由走小模型 route=%s via=%s reason=%s",
        decision.route,
        decision.via,
        decision.reason,
    )
    return decision
