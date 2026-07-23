"""库存预警 Skill：低于安全库存 / 高库龄 / 在途不足，并给出补货建议."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.db.mysql import SessionLocal

logger = logging.getLogger(__name__)

# 命中任一「预警意图」词 + 库存相关语境时启用本 Skill（确定性，无 LLM）
_ALERT_INTENT = (
    "预警",
    "告警",
    "低于安全库存",
    "低于安全",
    "安全库存",
    "缺货",
    "断货",
    "补货",
    "库龄",
    "滞销",
    "呆滞",
    "在途不足",
    "库存风险",
    "哪些.*低",
    "库存告警",
)

_INVENTORY_CONTEXT = (
    "库存",
    "可售",
    "在库",
    "在途",
    "sku",
    "仓库",
    "仓",
    "安全库存",
    "补货",
    "库龄",
)


@dataclass
class InventoryAlertItem:
    rule: str
    warehouse_code: str
    product_sku: str
    name_cn: str
    category: str
    available_qty: int
    safety_stock: int
    in_transit_qty: int
    aging_90_plus: int
    gap_qty: int
    suggestion: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "warehouse_code": self.warehouse_code,
            "product_sku": self.product_sku,
            "name_cn": self.name_cn,
            "category": self.category,
            "available_qty": self.available_qty,
            "safety_stock": self.safety_stock,
            "in_transit_qty": self.in_transit_qty,
            "aging_90_plus": self.aging_90_plus,
            "gap_qty": self.gap_qty,
            "suggestion": self.suggestion,
        }


@dataclass
class InventoryAlertResult:
    question: str
    matched: bool = False
    snapshot_date: str | None = None
    items: list[InventoryAlertItem] = field(default_factory=list)
    rule_notes: list[str] = field(default_factory=list)
    error: str | None = None

    def as_context(self) -> str:
        if self.error:
            return f"【库存预警】执行失败: {self.error}"
        if not self.matched:
            return ""
        if not self.items:
            date_line = f"（快照日 {self.snapshot_date}）" if self.snapshot_date else ""
            return f"【库存预警】{date_line}未发现低于安全库存、高库龄或在途缺口的 SKU。"

        lines = ["【库存预警】"]
        if self.snapshot_date:
            lines.append(f"库存快照日: {self.snapshot_date}")
        lines.append(
            "口径: 可售=available_qty（不含 reserved/in_transit）；"
            "缺口=max(safety_stock - available_qty, 0)；建议补货量≈缺口+安全库存缓冲。"
        )
        if self.rule_notes:
            lines.append("参考规范:")
            lines.extend(f"- {n}" for n in self.rule_notes[:4])

        lines.append(f"命中 {len(self.items)} 条（按优先级截断展示）:")
        for idx, item in enumerate(self.items[:30], start=1):
            lines.append(
                f"{idx}. [{item.rule}] {item.warehouse_code} / {item.product_sku} "
                f"({item.name_cn or '-'}, {item.category or '-'}) "
                f"可售={item.available_qty}, 安全库存={item.safety_stock}, "
                f"在途={item.in_transit_qty}, 库龄90+={item.aging_90_plus}, "
                f"缺口={item.gap_qty} → {item.suggestion}"
            )
        return "\n".join(lines)


class InventoryAlertSkill:
    """库存预警 Skill.

    规则（与 Demo 运营文档对齐）:
    1. below_safety: available_qty < safety_stock
    2. aging_90: aging_90_plus > 0 且占 on_hand 比例偏高（或绝对量>0 且可售偏高滞销）
    3. transit_gap: 可售低于安全库存且 in_transit 不足以补齐缺口
    """

    name = "inventory_alert"
    description = "扫描可售低于安全库存、高库龄、在途不足，并输出补货建议"

    def matches(self, question: str) -> bool:
        q = (question or "").strip().lower()
        if not q:
            return False
        has_alert = any(self._contains(pat, q) for pat in _ALERT_INTENT)
        has_inv = any(k in q for k in _INVENTORY_CONTEXT)
        # 「低于安全库存 / 补货建议」本身已足够
        strong = any(
            k in q
            for k in (
                "安全库存",
                "补货",
                "缺货",
                "断货",
                "库龄",
                "滞销",
                "库存预警",
                "库存告警",
            )
        )
        return strong or (has_alert and has_inv)

    @staticmethod
    def _contains(pattern: str, text: str) -> bool:
        if ".*" in pattern:
            return re.search(pattern, text) is not None
        return pattern in text

    def run(self, question: str, *, limit: int = 30) -> InventoryAlertResult:
        result = InventoryAlertResult(question=question, matched=True)
        if not self.matches(question):
            result.matched = False
            return result

        # 从问题里轻量抽仓库 / 品类过滤
        warehouse = self._extract_warehouse(question)
        category = self._extract_category(question)
        want_aging = any(k in question for k in ("库龄", "滞销", "呆滞"))
        want_safety = any(
            k in question for k in ("安全库存", "缺货", "断货", "补货", "预警", "告警", "低于")
        ) or not want_aging

        db = SessionLocal()
        try:
            snap = db.execute(
                text("SELECT MAX(snapshot_date) AS d FROM inventory_snapshots")
            ).mappings().first()
            snapshot_date = snap["d"] if snap else None
            if not snapshot_date:
                result.error = "inventory_snapshots 无数据"
                return result
            result.snapshot_date = str(snapshot_date)

            rows = self._fetch_snapshot_rows(
                db,
                snapshot_date=snapshot_date,
                warehouse=warehouse,
                category=category,
            )
            items: list[InventoryAlertItem] = []
            for row in rows:
                items.extend(
                    self._evaluate_row(
                        row,
                        include_safety=want_safety,
                        include_aging=want_aging or want_safety,
                    )
                )

            # 去重：同仓+SKU 保留优先级更高的规则
            priority = {"below_safety": 0, "transit_gap": 1, "aging_90": 2}
            best: dict[tuple[str, str], InventoryAlertItem] = {}
            for item in items:
                key = (item.warehouse_code, item.product_sku)
                prev = best.get(key)
                if prev is None or priority.get(item.rule, 9) < priority.get(prev.rule, 9):
                    best[key] = item

            ordered = sorted(
                best.values(),
                key=lambda x: (
                    priority.get(x.rule, 9),
                    -x.gap_qty,
                    -x.aging_90_plus,
                    x.warehouse_code,
                    x.product_sku,
                ),
            )
            result.items = ordered[:limit]
            result.rule_notes = self._default_rule_notes()
            # 可选：用 RAG 补运营规范摘要
            try:
                from app.agent.skills.rag import get_rag_skill

                rag = get_rag_skill().retrieve(
                    "安全库存 库龄 补货 周转率",
                    top_k=2,
                    categories=["operations"],
                )
                for hit in rag.hits:
                    note = f"{hit.title}: {hit.content[:160].replace(chr(10), ' ')}"
                    if note not in result.rule_notes:
                        result.rule_notes.append(note)
            except Exception as exc:  # noqa: BLE001
                logger.info("库存预警附带 RAG 规范跳过: %s", exc)

            logger.info(
                "库存预警 hits=%s warehouse=%s category=%s",
                len(result.items),
                warehouse,
                category,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("库存预警查询失败: %s", exc)
            result.error = str(exc)
            return result
        finally:
            db.close()

    def _fetch_snapshot_rows(
        self,
        db: Any,
        *,
        snapshot_date: Any,
        warehouse: str | None,
        category: str | None,
    ) -> list[Any]:
        sql = """
        SELECT
            s.warehouse_code,
            s.product_sku,
            s.available_qty,
            s.on_hand_qty,
            s.in_transit_qty,
            s.safety_stock,
            s.aging_90_plus,
            p.name_cn,
            p.category
        FROM inventory_snapshots s
        LEFT JOIN products p ON p.sku = s.product_sku
        WHERE s.snapshot_date = :snapshot_date
        """
        params: dict[str, Any] = {"snapshot_date": snapshot_date}
        if warehouse:
            sql += " AND s.warehouse_code = :warehouse"
            params["warehouse"] = warehouse
        if category:
            sql += " AND p.category = :category"
            params["category"] = category
        sql += " ORDER BY s.warehouse_code, s.product_sku LIMIT 500"
        return list(db.execute(text(sql), params).mappings().all())

    def _evaluate_row(
        self,
        row: Any,
        *,
        include_safety: bool,
        include_aging: bool,
    ) -> list[InventoryAlertItem]:
        available = int(row["available_qty"] or 0)
        safety = int(row["safety_stock"] or 0)
        in_transit = int(row["in_transit_qty"] or 0)
        aging_90 = int(row["aging_90_plus"] or 0)
        on_hand = int(row["on_hand_qty"] or 0)
        gap = max(safety - available, 0)
        base = dict(
            warehouse_code=str(row["warehouse_code"]),
            product_sku=str(row["product_sku"]),
            name_cn=str(row["name_cn"] or ""),
            category=str(row["category"] or ""),
            available_qty=available,
            safety_stock=safety,
            in_transit_qty=in_transit,
            aging_90_plus=aging_90,
            gap_qty=gap,
        )
        out: list[InventoryAlertItem] = []

        if include_safety and safety > 0 and available < safety:
            suggest_qty = gap + max(safety // 2, 1)
            covered = in_transit >= gap
            if not covered and gap > 0:
                out.append(
                    InventoryAlertItem(
                        rule="transit_gap",
                        suggestion=(
                            f"可售低于安全库存且在途({in_transit})不足以补缺口({gap})，"
                            f"建议加急补货约 {suggest_qty} 件并跟进在途 ETA"
                        ),
                        **base,
                    )
                )
            else:
                out.append(
                    InventoryAlertItem(
                        rule="below_safety",
                        suggestion=(
                            f"可售低于安全库存，建议补货约 {suggest_qty} 件"
                            + (f"（在途 {in_transit} 已覆盖缺口，持续盯到货）" if covered else "")
                        ),
                        **base,
                    )
                )

        if include_aging and aging_90 > 0 and (aging_90 >= 10 or (on_hand > 0 and aging_90 / max(on_hand, 1) >= 0.3)):
            out.append(
                InventoryAlertItem(
                    rule="aging_90",
                    suggestion="库龄>90 天占比较高，建议启动清货/站内促销或移仓，避免继续补货放大呆滞",
                    **base,
                )
            )
        return out

    @staticmethod
    def _default_rule_notes() -> list[str]:
        return [
            "可售库存口径=available_qty，不含 reserved / in_transit",
            "床类安全库存参考不低于 30，床头柜不低于 50（运营规范 Demo）",
            "库龄>90 天需清货或促销；>180 天必须提交处理方案",
            "补货量参考：未来需求 - 在库 - 在途 + 安全库存",
        ]

    @staticmethod
    def _extract_warehouse(question: str) -> str | None:
        m = re.search(r"\b([A-Z]{2}-[A-Z]{2}-\d+)\b", question.upper())
        return m.group(1) if m else None

    @staticmethod
    def _extract_category(question: str) -> str | None:
        mapping = {
            "bed": ("床类", "床架", "床垫", "床 "),
            "nightstand": ("床头柜", "床头柜类"),
            "dresser": ("斗柜", "梳妆"),
            "mattress": ("床垫",),
        }
        q = question.lower()
        # 英文 category
        for cat in ("bed", "nightstand", "dresser", "mattress"):
            if re.search(rf"\b{cat}\b", q):
                return cat
        for cat, aliases in mapping.items():
            if any(a in question for a in aliases):
                return cat
        return None


_inventory_alert_skill: InventoryAlertSkill | None = None


def get_inventory_alert_skill() -> InventoryAlertSkill:
    global _inventory_alert_skill
    if _inventory_alert_skill is None:
        _inventory_alert_skill = InventoryAlertSkill()
    return _inventory_alert_skill
