"""Agent 工具集."""

from langchain_core.tools import tool

from app.agent.skills.ad_diagnosis import get_ad_diagnosis_skill
from app.agent.skills.inventory_alert import get_inventory_alert_skill
from app.agent.skills.metrics_dictionary import get_metrics_dictionary_skill
from app.agent.skills.nl2sql import get_nl2sql_skill
from app.agent.skills.rag import get_rag_skill
from app.agent.skills.return_attribution import get_return_attribution_skill
from app.agent.skills.schema import ALLOWED_TABLES, SCHEMA_HINT

__all__ = [
    "ALLOWED_TABLES",
    "SCHEMA_HINT",
    "query_structured_data",
    "search_internal_knowledge",
    "nl2sql_query",
    "resolve_business_metrics",
    "inventory_alert_scan",
    "ad_diagnosis_scan",
    "return_attribution_scan",
    "TOOLS",
]


@tool
def query_structured_data(sql: str) -> str:
    """执行只读 SQL 查询傲基结构化业务数据（产品、订单、库存、退货、物流、广告等）。

    仅支持 SELECT，且只能查询白名单业务表。
    """
    return get_nl2sql_skill().execute_sql(sql)[0]


@tool
def resolve_business_metrics(question: str) -> str:
    """指标口径 Skill：识别问题中的 GMV/可售库存/ACOS 等指标并返回标准定义与公式。"""
    result = get_metrics_dictionary_skill().resolve(question)
    if not result.matched:
        return "未识别到已登记的业务指标；可直接按 Schema 查询，或补充指标别名到口径目录。"
    return result.as_context()


@tool
def inventory_alert_scan(question: str) -> str:
    """库存预警 Skill：扫描可售低于安全库存、高库龄、在途缺口，并给出补货建议。

    适用于「哪些 SKU 低于安全库存」「库龄过高要清货吗」「补货建议」等问题。
    """
    skill = get_inventory_alert_skill()
    if not skill.matches(question):
        result = skill.run(f"{question} 库存预警")
    else:
        result = skill.run(question)
    return result.as_context() or "未产生库存预警结果。"


@tool
def ad_diagnosis_scan(question: str) -> str:
    """广告诊断 Skill：扫描 ACOS 超标、空耗投放，并给出降出价/否定词建议。

    适用于「床类 ACOS 是否超标」「近7天广告诊断」「哪些投放该降出价」等问题。
    """
    skill = get_ad_diagnosis_skill()
    if not skill.matches(question):
        result = skill.run(f"{question} 广告诊断")
    else:
        result = skill.run(question)
    return result.as_context() or "未产生广告诊断结果。"


@tool
def return_attribution_scan(question: str) -> str:
    """退货归因 Skill：按 reason_code 分析退货分布，并给出物流/Listing/品质等归因建议。

    适用于「近30天退货原因分布」「破损是否偏高」「床类退货归因」等问题。
    """
    skill = get_return_attribution_skill()
    if not skill.matches(question):
        result = skill.run(f"{question} 退货归因")
    else:
        result = skill.run(question)
    return result.as_context() or "未产生退货归因结果。"


@tool
def nl2sql_query(question: str) -> str:
    """NL2SQL Skill：把自然语言问题转成安全 SELECT 并查询 MySQL。

    库存预警 / 广告诊断 / 退货归因类问题优先走对应规则 Skill。
    """
    inventory = get_inventory_alert_skill()
    if inventory.matches(question):
        return inventory.run(question).as_context()

    ads = get_ad_diagnosis_skill()
    if ads.matches(question):
        return ads.run(question).as_context()

    returns = get_return_attribution_skill()
    if returns.matches(question):
        return returns.run(question).as_context()

    metrics = get_metrics_dictionary_skill().resolve(question)
    result = get_nl2sql_skill().run(question, metric_context=metrics.as_prompt())
    parts = [p for p in (metrics.as_context(), result.as_context()) if p]
    return "\n\n".join(parts)


@tool
def search_internal_knowledge(query: str, top_k: int = 4, category: str = "") -> str:
    """RAG Skill：检索傲基内部知识（政策、流程、产品手册、运营/合规/广告规范等）。

    支持可选 category 过滤（如 policy、operations、ads、compliance）。
    """
    categories = [category.strip()] if category and category.strip() else None
    result = get_rag_skill().retrieve(query, top_k=top_k, categories=categories)
    return result.as_context()


TOOLS = [
    resolve_business_metrics,
    inventory_alert_scan,
    ad_diagnosis_scan,
    return_attribution_scan,
    nl2sql_query,
    query_structured_data,
    search_internal_knowledge,
]
