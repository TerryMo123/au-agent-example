"""退货归因 Skill：按原因码聚合退货，并给出业务归因与处置建议."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from app.db.mysql import SessionLocal

logger = logging.getLogger(__name__)

REASON_META: dict[str, dict[str, str]] = {
    "damaged": {
        "label": "运输破损/包装损坏",
        "attribution": "物流/包装",
        "suggestion": "排查头程/尾程装卸与外箱强度；大件加强角撑与填充，复盘承运商破损率",
        "rag_hint": "退货 破损 包装 尾程",
    },
    "size_issue": {
        "label": "尺寸不合适",
        "attribution": "Listing/期望管理",
        "suggestion": "补齐尺寸图与承重说明，标题突出实际尺寸，减少「偏小/偏大」预期差",
        "rag_hint": "Listing 尺寸 上架",
    },
    "not_as_described": {
        "label": "与描述不符",
        "attribution": "Listing/内容一致性",
        "suggestion": "核对主图/A+ 与实物一致性，禁止夸大材质与功能描述",
        "rag_hint": "Listing 描述 上架检查",
    },
    "changed_mind": {
        "label": "买家改变主意",
        "attribution": "买家原因（政策内）",
        "suggestion": "属正常退货窗口行为；关注是否集中在大促后，优化详情页决策信息即可",
        "rag_hint": "退货政策 退货窗口",
    },
    "missing_parts": {
        "label": "配件缺失",
        "attribution": "工厂装箱/质检",
        "suggestion": "检查 HARDWARE 单独装箱与五金件齐全率，出货前核对配件清单",
        "rag_hint": "配件 质检 FBA 标签 HARDWARE",
    },
    "quality": {
        "label": "做工/异味问题",
        "attribution": "品质/质检",
        "suggestion": "对照品类质检标准复检批次；异味类引导通风 SOP，结构性问题走退货退款",
        "rag_hint": "质检 异味 客诉",
    },
}

_ATTR_INTENT = (
    "退货归因",
    "退货原因",
    "退货分布",
    "退货分析",
    "为什么退货",
    "退货高",
    "破损偏高",
    "退货率高",
    "退款原因",
    "售后归因",
    "reason_code",
)

_RETURN_CONTEXT = ("退货", "退款", "售后", "rma", "破损", "配件缺失", "异味")


@dataclass
class ReturnReasonStat:
    reason_code: str
    label: str
    attribution: str
    count: int
    quantity: int
    refund_usd: float
    share_pct: float
    suggestion: str


@dataclass
class ReturnSkuStat:
    product_sku: str
    name_cn: str
    category: str
    count: int
    refund_usd: float
    top_reason: str


@dataclass
class ReturnAttributionResult:
    question: str
    matched: bool = False
    window_days: int = 30
    date_from: str | None = None
    date_to: str | None = None
    total_returns: int = 0
    total_refund_usd: float = 0.0
    reasons: list[ReturnReasonStat] = field(default_factory=list)
    top_skus: list[ReturnSkuStat] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    rule_notes: list[str] = field(default_factory=list)
    error: str | None = None

    def as_context(self) -> str:
        if self.error:
            return f"【退货归因】执行失败: {self.error}"
        if not self.matched:
            return ""
        if self.total_returns <= 0:
            return (
                f"【退货归因】近 {self.window_days} 天"
                f"（{self.date_from} ~ {self.date_to}）无退货记录。"
            )

        lines = [
            "【退货归因】",
            f"统计窗口: 近 {self.window_days} 天（{self.date_from} ~ {self.date_to}）",
            f"退货单数={self.total_returns}，退款金额=${self.total_refund_usd:.2f}",
            "口径: 按 returns.opened_date；金额用 refund_amount_usd；原因用 reason_code",
        ]
        if self.rule_notes:
            lines.append("参考规范:")
            lines.extend(f"- {n}" for n in self.rule_notes[:4])
        if self.highlights:
            lines.append("关键结论:")
            lines.extend(f"- {h}" for h in self.highlights)

        lines.append("原因分布:")
        for idx, r in enumerate(self.reasons, start=1):
            lines.append(
                f"{idx}. {r.reason_code}（{r.label}）占比 {r.share_pct:.1f}% | "
                f"单数={r.count}, 件数={r.quantity}, 退款=${r.refund_usd:.2f} | "
                f"归因={r.attribution} → {r.suggestion}"
            )

        if self.top_skus:
            lines.append("退货金额 Top SKU:")
            for idx, s in enumerate(self.top_skus[:10], start=1):
                lines.append(
                    f"{idx}. {s.product_sku} ({s.name_cn or '-'}, {s.category or '-'}) "
                    f"单数={s.count}, 退款=${s.refund_usd:.2f}, 主因={s.top_reason}"
                )
        return "\n".join(lines)


class ReturnAttributionSkill:
    """退货归因 Skill.

    聚合 returns.reason_code，结合内部规范给出「物流破损 / Listing / 品质」等归因建议。
    """

    name = "return_attribution"
    description = "分析退货原因分布并给出业务归因与处置建议"

    def matches(self, question: str) -> bool:
        q = (question or "").strip().lower()
        if not q:
            return False
        if any(k in q for k in _ATTR_INTENT):
            return True
        has_return = any(k in q for k in _RETURN_CONTEXT)
        has_attr = any(
            k in q
            for k in (
                "归因",
                "原因",
                "分布",
                "分析",
                "为什么",
                "偏高",
                "过高",
                "主要",
                "哪里",
                "哪类",
            )
        )
        return has_return and has_attr

    def run(
        self, question: str, *, window_days: int | None = None, top_sku_n: int = 8
    ) -> ReturnAttributionResult:
        result = ReturnAttributionResult(question=question, matched=True)
        if not self.matches(question):
            result.matched = False
            return result

        days = window_days or self._extract_days(question) or 30
        result.window_days = days
        site = self._extract_site(question)
        marketplace = self._extract_marketplace(question)
        category = self._extract_category(question)

        db = SessionLocal()
        try:
            bounds = db.execute(
                text("SELECT MAX(opened_date) AS d FROM returns")
            ).mappings().first()
            date_to = bounds["d"] if bounds else None
            if not date_to:
                result.error = "returns 无数据"
                return result
            date_from = date_to - timedelta(days=days - 1)
            result.date_from = str(date_from)
            result.date_to = str(date_to)

            reason_rows = self._fetch_reason_agg(
                db,
                date_from=date_from,
                date_to=date_to,
                site=site,
                marketplace=marketplace,
                category=category,
            )
            sku_rows = self._fetch_sku_agg(
                db,
                date_from=date_from,
                date_to=date_to,
                site=site,
                marketplace=marketplace,
                category=category,
                limit=top_sku_n,
            )

            total_count = sum(int(r["cnt"] or 0) for r in reason_rows)
            total_refund = sum(float(r["refund_usd"] or 0) for r in reason_rows)
            result.total_returns = total_count
            result.total_refund_usd = total_refund

            reasons: list[ReturnReasonStat] = []
            for row in reason_rows:
                code = str(row["reason_code"] or "unknown")
                meta = REASON_META.get(
                    code,
                    {
                        "label": code,
                        "attribution": "待人工确认",
                        "suggestion": "建议抽检原始客诉与质检记录后再定责",
                    },
                )
                cnt = int(row["cnt"] or 0)
                share = (cnt / total_count * 100) if total_count else 0.0
                reasons.append(
                    ReturnReasonStat(
                        reason_code=code,
                        label=str(meta["label"]),
                        attribution=str(meta["attribution"]),
                        count=cnt,
                        quantity=int(row["qty"] or 0),
                        refund_usd=float(row["refund_usd"] or 0),
                        share_pct=share,
                        suggestion=str(meta["suggestion"]),
                    )
                )
            result.reasons = reasons

            top_skus: list[ReturnSkuStat] = []
            for row in sku_rows:
                top_skus.append(
                    ReturnSkuStat(
                        product_sku=str(row["product_sku"]),
                        name_cn=str(row["name_cn"] or ""),
                        category=str(row["category"] or ""),
                        count=int(row["cnt"] or 0),
                        refund_usd=float(row["refund_usd"] or 0),
                        top_reason=str(row["top_reason"] or ""),
                    )
                )
            result.top_skus = top_skus
            result.highlights = self._build_highlights(reasons)
            result.rule_notes = [
                "美国站 Amazon 订单 30 天内可申请退货（政策 Demo）",
                "运输破损优先补发配件；结构性损坏可退货退款",
                "异味类：引导通风 48-72 小时，仍不接受则走退货",
            ]

            # 按 Top 原因拉一点相关规范
            try:
                from app.agent.skills.rag import get_rag_skill

                top_codes = [r.reason_code for r in reasons[:2]]
                hints = []
                for code in top_codes:
                    hint = REASON_META.get(code, {}).get("rag_hint")
                    if hint:
                        hints.append(hint)
                query = " ".join(hints) if hints else "退货 破损 质检"
                rag = get_rag_skill().retrieve(
                    query,
                    top_k=2,
                    categories=["policy", "logistics", "product", "customer_service"],
                )
                for hit in rag.hits:
                    note = f"{hit.title}: {hit.content[:140].replace(chr(10), ' ')}"
                    if note not in result.rule_notes:
                        result.rule_notes.append(note)
            except Exception as exc:  # noqa: BLE001
                logger.info("退货归因附带 RAG 跳过: %s", exc)

            logger.info(
                "退货归因 reasons=%s total=%s days=%s",
                len(result.reasons),
                result.total_returns,
                days,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("退货归因查询失败: %s", exc)
            result.error = str(exc)
            return result
        finally:
            db.close()

    def _fetch_reason_agg(
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
            r.reason_code,
            COUNT(*) AS cnt,
            SUM(r.quantity) AS qty,
            SUM(r.refund_amount_usd) AS refund_usd
        FROM returns r
        LEFT JOIN products p ON p.sku = r.product_sku
        WHERE r.opened_date BETWEEN :date_from AND :date_to
        """
        params: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
        if site:
            sql += " AND r.site = :site"
            params["site"] = site
        if marketplace:
            sql += " AND r.marketplace = :marketplace"
            params["marketplace"] = marketplace
        if category:
            sql += " AND p.category = :category"
            params["category"] = category
        sql += " GROUP BY r.reason_code ORDER BY cnt DESC"
        return list(db.execute(text(sql), params).mappings().all())

    def _fetch_sku_agg(
        self,
        db: Any,
        *,
        date_from: date,
        date_to: date,
        site: str | None,
        marketplace: str | None,
        category: str | None,
        limit: int,
    ) -> list[Any]:
        # 先按 SKU 汇总，再取该 SKU 主因
        sql = """
        SELECT
            t.product_sku,
            t.name_cn,
            t.category,
            t.cnt,
            t.refund_usd,
            (
                SELECT r2.reason_code
                FROM returns r2
                WHERE r2.product_sku = t.product_sku
                  AND r2.opened_date BETWEEN :date_from AND :date_to
                GROUP BY r2.reason_code
                ORDER BY COUNT(*) DESC
                LIMIT 1
            ) AS top_reason
        FROM (
            SELECT
                r.product_sku,
                p.name_cn,
                p.category,
                COUNT(*) AS cnt,
                SUM(r.refund_amount_usd) AS refund_usd
            FROM returns r
            LEFT JOIN products p ON p.sku = r.product_sku
            WHERE r.opened_date BETWEEN :date_from AND :date_to
        """
        params: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
        }
        if site:
            sql += " AND r.site = :site"
            params["site"] = site
        if marketplace:
            sql += " AND r.marketplace = :marketplace"
            params["marketplace"] = marketplace
        if category:
            sql += " AND p.category = :category"
            params["category"] = category
        sql += """
            GROUP BY r.product_sku, p.name_cn, p.category
            ORDER BY refund_usd DESC
            LIMIT :limit
        ) t
        """
        return list(db.execute(text(sql), params).mappings().all())

    @staticmethod
    def _build_highlights(reasons: list[ReturnReasonStat]) -> list[str]:
        if not reasons:
            return []
        highlights: list[str] = []
        top = reasons[0]
        highlights.append(
            f"主因是 {top.reason_code}（{top.label}），占比 {top.share_pct:.1f}%，"
            f"优先按「{top.attribution}」方向处理"
        )
        damaged = next((r for r in reasons if r.reason_code == "damaged"), None)
        if damaged and damaged.share_pct >= 25:
            highlights.append(
                f"破损类占比 {damaged.share_pct:.1f}% 偏高，怀疑头程/尾程或包装问题，"
                "建议同步质检与物流复盘"
            )
        quality = next((r for r in reasons if r.reason_code == "quality"), None)
        if quality and quality.share_pct >= 20:
            highlights.append(
                f"品质/异味占比 {quality.share_pct:.1f}%，建议抽检近批工厂质检与包装通风措施"
            )
        missing = next((r for r in reasons if r.reason_code == "missing_parts"), None)
        if missing and missing.share_pct >= 15:
            highlights.append(
                f"配件缺失占比 {missing.share_pct:.1f}%，优先核查 HARDWARE 装箱与出货核对"
            )
        return highlights

    @staticmethod
    def _extract_days(question: str) -> int | None:
        m = re.search(r"近\s*(\d+)\s*天", question)
        if m:
            return max(1, min(int(m.group(1)), 180))
        m = re.search(r"近\s*(\d+)\s*个?月", question)
        if m:
            return max(1, min(int(m.group(1)) * 30, 180))
        if "上个月" in question or "上月" in question:
            return 30
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
        if "床头柜" in question or "nightstand" in question.lower():
            return "nightstand"
        if re.search(r"\bbed\b", question.lower()) or "床类" in question or "床架" in question:
            return "bed"
        if "斗柜" in question or "dresser" in question.lower():
            return "dresser"
        if "床垫" in question or "mattress" in question.lower():
            return "mattress"
        return None


_return_attribution_skill: ReturnAttributionSkill | None = None


def get_return_attribution_skill() -> ReturnAttributionSkill:
    global _return_attribution_skill
    if _return_attribution_skill is None:
        _return_attribution_skill = ReturnAttributionSkill()
    return _return_attribution_skill
