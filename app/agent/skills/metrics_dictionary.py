"""指标口径 Skill：识别问题中的业务指标并输出标准口径，供 NL2SQL / 回答引用。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.agent.skills.metrics_catalog import METRIC_CATALOG, MetricDef

logger = logging.getLogger(__name__)


@dataclass
class MetricsResolveResult:
    question: str
    matched: list[MetricDef] = field(default_factory=list)

    @property
    def matched_keys(self) -> list[str]:
        return [m.key for m in self.matched]

    def as_prompt(self) -> str:
        """注入 NL2SQL 的口径约束文本."""
        if not self.matched:
            return ""
        lines = ["【必须遵守的指标口径】"]
        for m in self.matched:
            lines.append(
                f"- {m.name_cn}({m.key}): {m.definition} "
                f"公式={m.formula}；SQL提示={m.sql_hint}"
                + (f"；注意={m.notes}" if m.notes else "")
            )
        return "\n".join(lines)

    def as_context(self) -> str:
        """给最终回答引用的口径说明."""
        if not self.matched:
            return ""
        blocks = ["【指标口径】"]
        for m in self.matched:
            blocks.append(
                f"- {m.name_cn}: {m.definition}\n"
                f"  公式: {m.formula}\n"
                f"  推荐表字段: {', '.join(m.preferred_tables)} / {', '.join(m.preferred_fields)}"
                + (f"\n  备注: {m.notes}" if m.notes else "")
            )
        return "\n".join(blocks)


class MetricsDictionarySkill:
    """指标口径 Skill.

    先做别名/关键词匹配（确定性、低延迟），把标准口径传给 NL2SQL，
    降低「同词不同算法」导致的错误 SQL。
    """

    name = "metrics_dictionary"
    description = "识别 GMV/可售库存/ACOS 等指标并给出标准口径与 SQL 提示"

    def __init__(self) -> None:
        # (alias_lower, metric) 长别名优先，避免短词误伤
        pairs: list[tuple[str, MetricDef]] = []
        for metric in METRIC_CATALOG:
            for alias in metric.aliases + (metric.name_cn, metric.key):
                a = alias.strip().lower()
                if a:
                    pairs.append((a, metric))
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        self._alias_pairs = pairs

    def resolve(self, question: str) -> MetricsResolveResult:
        q = (question or "").strip()
        q_lower = q.lower()
        matched: list[MetricDef] = []
        seen: set[str] = set()

        for alias, metric in self._alias_pairs:
            if metric.key in seen:
                continue
            if self._alias_in_text(alias, q_lower):
                matched.append(metric)
                seen.add(metric.key)

        if matched:
            logger.info("指标口径命中: %s", [m.key for m in matched])
        return MetricsResolveResult(question=q, matched=matched)

    @staticmethod
    def _alias_in_text(alias: str, text_lower: str) -> bool:
        if not alias:
            return False
        # 英文/数字别名用词边界；中文直接子串
        if re.fullmatch(r"[a-z0-9_\s\-]+", alias):
            pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
            return re.search(pattern, text_lower) is not None
        return alias in text_lower

    def run(self, question: str) -> MetricsResolveResult:
        return self.resolve(question)

    def list_metrics(self) -> list[dict[str, str]]:
        return [
            {
                "key": m.key,
                "name_cn": m.name_cn,
                "definition": m.definition,
                "formula": m.formula,
            }
            for m in METRIC_CATALOG
        ]


_metrics_skill: MetricsDictionarySkill | None = None


def get_metrics_dictionary_skill() -> MetricsDictionarySkill:
    global _metrics_skill
    if _metrics_skill is None:
        _metrics_skill = MetricsDictionarySkill()
    return _metrics_skill
