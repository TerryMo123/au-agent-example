"""Agent Skills 注册表."""

from app.agent.skills.ad_diagnosis import AdDiagnosisSkill, get_ad_diagnosis_skill
from app.agent.skills.inventory_alert import (
    InventoryAlertSkill,
    get_inventory_alert_skill,
)
from app.agent.skills.metrics_dictionary import (
    MetricsDictionarySkill,
    get_metrics_dictionary_skill,
)
from app.agent.skills.nl2sql import NL2SQLSkill, get_nl2sql_skill
from app.agent.skills.rag import RagSkill, get_rag_skill
from app.agent.skills.return_attribution import (
    ReturnAttributionSkill,
    get_return_attribution_skill,
)

__all__ = [
    "NL2SQLSkill",
    "get_nl2sql_skill",
    "MetricsDictionarySkill",
    "get_metrics_dictionary_skill",
    "RagSkill",
    "get_rag_skill",
    "InventoryAlertSkill",
    "get_inventory_alert_skill",
    "AdDiagnosisSkill",
    "get_ad_diagnosis_skill",
    "ReturnAttributionSkill",
    "get_return_attribution_skill",
]
