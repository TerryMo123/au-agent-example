"""广告诊断 Skill：ACOS/ROAS 超标扫描与处置建议."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from app.db.mysql import SessionLocal

logger = logging.getLogger(__name__)

# 成熟款目标 ACOS（比率，非百分数）：与 ads-acos-001 文档对齐
TARGET_ACOS_BY_CATEGORY: dict[str, float] = {
    "bed": 0.25,
    "nightstand": 0.30,
    "dresser": 0.30,
    "mattress": 0.28,
}
DEFAULT_TARGET_ACOS = 0.30
CRITICAL_MULTIPLIER = 1.5  # 超目标 1.5 倍 → 强制降出价

_DIAG_INTENT = (
    "广告诊断",
    "广告超标",
    "acos 超",
    "acos超",
    "超 acos",
    "超acos",
    "acos 高",
    "acos高",
    "投放诊断",
    "降出价",
    "否定关键词",
    "广告浪费",
    "无效投放",
    "roas 低",
    "roas低",
    "广告预警",
    "广告告警",
    "诊断广告",
)

_AD_CONTEXT = (
    "广告",
    "acos",
    "roas",
    "投放",
    "花费",
    "出价",
    "campaign",
)


@dataclass
class AdDiagnosisItem:
    rule: str
    product_sku: str
    name_cn: str
    category: str
    marketplace: str
    site: str
    spend_usd: float
    ad_sales_usd: float
    acos: float | None
    roas: float | None
    target_acos: float
    suggestion: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "product_sku": self.product_sku,
            "name_cn": self.name_cn,
            "category": self.category,
            "marketplace": self.marketplace,
            "site": self.site,
            "spend_usd": self.spend_usd,
            "ad_sales_usd": self.ad_sales_usd,
            "acos": self.acos,
            "roas": self.roas,
            "target_acos": self.target_acos,
            "suggestion": self.suggestion,
        }


@dataclass
class AdDiagnosisResult:
    question: str
    matched: bool = False
    window_days: int = 7
    date_from: str | None = None
    date_to: str | None = None
    items: list[AdDiagnosisItem] = field(default_factory=list)
    rule_notes: list[str] = field(default_factory=list)
    error: str | None = None

    def as_context(self) -> str:
        if self.error:
            return f"【广告诊断】执行失败: {self.error}"
        if not self.matched:
            return ""
        if not self.items:
            return (
                f"【广告诊断】近 {self.window_days} 天"
                f"（{self.date_from} ~ {self.date_to}）未发现 ACOS 超标或空耗投放。"
            )

        lines = [
            "【广告诊断】",
            f"统计窗口: 近 {self.window_days} 天（{self.date_from} ~ {self.date_to}）",
            "口径: ACOS = SUM(spend_usd)/NULLIF(SUM(ad_sales_usd),0)；"
            "ROAS = SUM(ad_sales_usd)/NULLIF(SUM(spend_usd),0)",
        ]
        if self.rule_notes:
            lines.append("参考规范:")
            lines.extend(f"- {n}" for n in self.rule_notes[:5])
        lines.append(f"命中 {len(self.items)} 条（按严重度排序）:")
        for idx, item in enumerate(self.items[:30], start=1):
            acos_pct = f"{item.acos * 100:.1f}%" if item.acos is not None else "-"
            target_pct = f"{item.target_acos * 100:.0f}%"
            roas_s = f"{item.roas:.2f}" if item.roas is not None else "-"
            lines.append(
                f"{idx}. [{item.rule}] {item.marketplace}/{item.site} "
                f"{item.product_sku} ({item.name_cn or '-'}, {item.category or '-'}) "
                f"花费=${item.spend_usd:.2f}, 广告销售=${item.ad_sales_usd:.2f}, "
                f"ACOS={acos_pct}(目标{target_pct}), ROAS={roas_s} → {item.suggestion}"
            )
        return "\n".join(lines)


class AdDiagnosisSkill:
    """广告诊断 Skill.

    规则（对齐傲基广告 ACOS 管控规范 Demo）:
    1. acos_critical: ACOS > 目标 × 1.5 → 建议降出价 10% 并预警
    2. acos_over_target: ACOS > 目标 → 复盘搜索词/出价
    3. spend_no_sales: 有花费无广告销售 → 暂停或大幅缩量
    """

    name = "ad_diagnosis"
    description = "诊断广告 ACOS/ROAS 超标与空耗投放，并给出降出价等建议"

    def matches(self, question: str) -> bool:
        q = (question or "").strip().lower()
        if not q:
            return False
        strong = any(self._contains(p, q) for p in _DIAG_INTENT)
        if strong:
            return True
        has_ad = any(k in q for k in _AD_CONTEXT)
        has_diag = any(
            k in q
            for k in (
                "诊断",
                "超标",
                "过高",
                "太高",
                "异常",
                "预警",
                "告警",
                "优化",
                "怎么调",
                "如何降",
                "是否超",
            )
        )
        # 「床类 ACOS 是否超标」「广告花费是否健康」
        return has_ad and has_diag

    @staticmethod
    def _contains(pattern: str, text: str) -> bool:
        return pattern in text

    def run(self, question: str, *, limit: int = 30, window_days: int | None = None) -> AdDiagnosisResult:
        result = AdDiagnosisResult(question=question, matched=True)
        if not self.matches(question):
            result.matched = False
            return result

        days = window_days or self._extract_days(question) or 7
        result.window_days = days
        site = self._extract_site(question)
        marketplace = self._extract_marketplace(question)
        category = self._extract_category(question)

        db = SessionLocal()
        try:
            bounds = db.execute(
                text("SELECT MAX(spend_date) AS d FROM ad_spend_daily")
            ).mappings().first()
            date_to = bounds["d"] if bounds else None
            if not date_to:
                result.error = "ad_spend_daily 无数据"
                return result
            date_from = date_to - timedelta(days=days - 1)
            result.date_from = str(date_from)
            result.date_to = str(date_to)

            rows = self._fetch_agg(
                db,
                date_from=date_from,
                date_to=date_to,
                site=site,
                marketplace=marketplace,
                category=category,
            )
            items: list[AdDiagnosisItem] = []
            for row in rows:
                items.extend(self._evaluate_row(row))

            priority = {"spend_no_sales": 0, "acos_critical": 1, "acos_over_target": 2}
            ordered = sorted(
                items,
                key=lambda x: (
                    priority.get(x.rule, 9),
                    -(x.acos or 0),
                    -x.spend_usd,
                ),
            )
            # 同 SKU+站点保留最严重一条
            best: dict[tuple[str, str, str], AdDiagnosisItem] = {}
            for item in ordered:
                key = (item.product_sku, item.marketplace, item.site)
                if key not in best:
                    best[key] = item
            result.items = list(best.values())[:limit]
            result.items.sort(
                key=lambda x: (priority.get(x.rule, 9), -(x.acos or 0), -x.spend_usd)
            )
            result.rule_notes = self._default_rule_notes()
            try:
                from app.agent.skills.rag import get_rag_skill

                rag = get_rag_skill().retrieve(
                    "ACOS 管控 降出价 否定关键词",
                    top_k=2,
                    categories=["ads"],
                )
                for hit in rag.hits:
                    note = f"{hit.title}: {hit.content[:160].replace(chr(10), ' ')}"
                    if note not in result.rule_notes:
                        result.rule_notes.append(note)
            except Exception as exc:  # noqa: BLE001
                logger.info("广告诊断附带 RAG 规范跳过: %s", exc)

            logger.info(
                "广告诊断 hits=%s days=%s site=%s category=%s",
                len(result.items),
                days,
                site,
                category,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("广告诊断查询失败: %s", exc)
            result.error = str(exc)
            return result
        finally:
            db.close()

    def _fetch_agg(
        self,
        db: Any,
        *,
        date_from: date,
        date_to: date,
        site: str | None,
        marketplace: str | None,
        category: str | None,
    ) -> list[Any]:
        sql = """
        SELECT
            a.product_sku,
            a.marketplace,
            a.site,
            SUM(a.spend_usd) AS spend_usd,
            SUM(a.ad_sales_usd) AS ad_sales_usd,
            p.name_cn,
            p.category
        FROM ad_spend_daily a
        LEFT JOIN products p ON p.sku = a.product_sku
        WHERE a.spend_date BETWEEN :date_from AND :date_to
        """
        params: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
        if site:
            sql += " AND a.site = :site"
            params["site"] = site
        if marketplace:
            sql += " AND a.marketplace = :marketplace"
            params["marketplace"] = marketplace
        if category:
            sql += " AND p.category = :category"
            params["category"] = category
        sql += """
        GROUP BY a.product_sku, a.marketplace, a.site, p.name_cn, p.category
        HAVING SUM(a.spend_usd) > 0
        ORDER BY SUM(a.spend_usd) DESC
        LIMIT 300
        """
        return list(db.execute(text(sql), params).mappings().all())

    def _evaluate_row(self, row: Any) -> list[AdDiagnosisItem]:
        spend = float(row["spend_usd"] or 0)
        ad_sales = float(row["ad_sales_usd"] or 0)
        category = str(row["category"] or "")
        target = TARGET_ACOS_BY_CATEGORY.get(category, DEFAULT_TARGET_ACOS)
        acos = (spend / ad_sales) if ad_sales > 0 else None
        roas = (ad_sales / spend) if spend > 0 else None
        base = dict(
            product_sku=str(row["product_sku"]),
            name_cn=str(row["name_cn"] or ""),
            category=category,
            marketplace=str(row["marketplace"]),
            site=str(row["site"]),
            spend_usd=spend,
            ad_sales_usd=ad_sales,
            acos=acos,
            roas=roas,
            target_acos=target,
        )
        out: list[AdDiagnosisItem] = []

        if ad_sales <= 0 and spend >= 20:
            out.append(
                AdDiagnosisItem(
                    rule="spend_no_sales",
                    suggestion="有花费几乎无广告销售，建议暂停该投放或大幅缩量，并清理无效搜索词",
                    **base,
                )
            )
            return out

        if acos is None:
            return out

        if acos > target * CRITICAL_MULTIPLIER:
            out.append(
                AdDiagnosisItem(
                    rule="acos_critical",
                    suggestion=(
                        f"ACOS 超过目标 {target * 100:.0f}% 的 1.5 倍，"
                        "建议立即降出价 10% 并复盘否定关键词"
                    ),
                    **base,
                )
            )
        elif acos > target:
            out.append(
                AdDiagnosisItem(
                    rule="acos_over_target",
                    suggestion=(
                        f"ACOS 高于目标 {target * 100:.0f}%，"
                        "建议降出价 5%-10%，收紧匹配并否定低效词"
                    ),
                    **base,
                )
            )
        return out

    @staticmethod
    def _default_rule_notes() -> list[str]:
        return [
            "成熟款目标 ACOS：床类 ≤25%，床头柜 ≤30%",
            "连续超目标 1.5 倍：自动降出价 10% 并预警",
            "否定关键词每周至少复盘一次",
            "ACOS = 广告花费 / 广告销售额（比率）",
        ]

    @staticmethod
    def _extract_days(question: str) -> int | None:
        m = re.search(r"近\s*(\d+)\s*天", question)
        if m:
            return max(1, min(int(m.group(1)), 90))
        m = re.search(r"(\d+)\s*天", question)
        if m and ("近" in question or "过去" in question or "最近" in question):
            return max(1, min(int(m.group(1)), 90))
        return None

    @staticmethod
    def _extract_site(question: str) -> str | None:
        q = question.upper()
        for site in ("US", "UK", "DE", "CA"):
            if re.search(rf"\b{site}\b", q) or f"{site}站" in question.upper():
                return site
        if "美国" in question:
            return "US"
        if "英国" in question:
            return "UK"
        if "德国" in question:
            return "DE"
        if "加拿大" in question:
            return "CA"
        return None

    @staticmethod
    def _extract_marketplace(question: str) -> str | None:
        mapping = {
            "Amazon": ("amazon", "亚马逊"),
            "Wayfair": ("wayfair",),
            "Walmart": ("walmart", "沃尔玛"),
            "OTTO": ("otto",),
        }
        q = question.lower()
        for name, aliases in mapping.items():
            if any(a in q for a in aliases):
                return name
        return None

    @staticmethod
    def _extract_category(question: str) -> str | None:
        if re.search(r"\bbed\b", question.lower()) or "床类" in question or "床架" in question:
            return "bed"
        if "床头柜" in question or "nightstand" in question.lower():
            return "nightstand"
        if "斗柜" in question or "dresser" in question.lower():
            return "dresser"
        if "床垫" in question or "mattress" in question.lower():
            return "mattress"
        return None


_ad_diagnosis_skill: AdDiagnosisSkill | None = None


def get_ad_diagnosis_skill() -> AdDiagnosisSkill:
    global _ad_diagnosis_skill
    if _ad_diagnosis_skill is None:
        _ad_diagnosis_skill = AdDiagnosisSkill()
    return _ad_diagnosis_skill
