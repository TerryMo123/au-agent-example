"""NL2SQL Skill：自然语言 → 安全 SQL → 执行查询."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import SystemMessage
from sqlalchemy import text

from app.agent.skills.schema import (
    ALLOWED_TABLES,
    DANGEROUS_SQL_KEYWORDS,
    FEW_SHOT_EXAMPLES,
    SCHEMA_HINT,
)
from app.agent.viz import serialize_rows
from app.db.mysql import SessionLocal
from app.llm import get_chat_llm
from app.llm_retry import LLMRetryExhaustedError, invoke_llm_with_retry

logger = logging.getLogger(__name__)


@dataclass
class NL2SQLResult:
    """NL2SQL 执行结果."""

    question: str
    sql: str = ""
    rows_preview: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False
    repaired: bool = False
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_context(self) -> str:
        if self.success:
            prefix = "【NL2SQL 查询成功"
            if self.repaired:
                prefix += "（含一次自动修复）"
            prefix += f"】\nSQL: {self.sql}\n结果: {self.rows_preview}"
            return prefix
        return (
            f"【NL2SQL 查询失败】\n"
            f"SQL: {self.sql or '(未生成)'}\n"
            f"原因: {self.error or '未知错误'}"
        )


class NL2SQLSkill:
    """傲基业务库 NL2SQL Skill.

    能力:
    1. 基于白名单 Schema 将自然语言转为 SELECT
    2. 校验只读与表白名单
    3. 执行查询
    4. 执行失败时带错误信息自动修复一次
    """

    name = "nl2sql"
    description = "将自然语言转为 MySQL 只读查询并执行，用于销量/库存/订单等结构化问答"

    def __init__(self) -> None:
        self.llm = get_chat_llm(temperature=0)

    def clean_sql(self, raw: str) -> str:
        sql = raw.strip()
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*```$", "", sql)
        sql = sql.strip().strip("`")
        # 去掉模型可能加的前缀
        sql = re.sub(r"^(sql|mysql)\s*[:：]\s*", "", sql, flags=re.IGNORECASE)
        return sql.strip()

    def validate_sql(self, sql: str) -> str | None:
        """返回错误信息；通过则返回 None."""
        if not sql:
            return "SQL 为空"
        normalized = sql.strip().lower()
        if not normalized.startswith("select"):
            return "仅允许 SELECT 查询"
        if ";" in normalized.rstrip(";"):
            return "不允许一次执行多条语句"
        if any(k in normalized for k in DANGEROUS_SQL_KEYWORDS):
            return "检测到危险 SQL 关键字"
        if not any(table in normalized for table in ALLOWED_TABLES):
            return f"只能查询白名单表: {', '.join(sorted(ALLOWED_TABLES))}"
        return None

    def execute_sql(self, sql: str, *, limit: int = 50) -> tuple[str, list[dict[str, Any]]]:
        err = self.validate_sql(sql)
        if err:
            return f"错误: {err}", []

        db = SessionLocal()
        try:
            result = db.execute(text(sql))
            raw_rows = result.mappings().all()
            if not raw_rows:
                return "查询成功，无结果。", []
            rows = serialize_rows([dict(r) for r in raw_rows[:limit]])
            return str(rows), rows
        except Exception as exc:  # noqa: BLE001
            return f"SQL 执行失败: {exc}", []
        finally:
            db.close()

    @staticmethod
    def _truncate_knowledge(text: str, *, max_chars: int = 1800) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max_chars - 1] + "…"

    def _build_generate_prompt(
        self,
        question: str,
        metric_context: str = "",
        knowledge_context: str = "",
    ) -> str:
        metrics_block = f"\n{metric_context}\n" if metric_context.strip() else ""
        knowledge = self._truncate_knowledge(knowledge_context)
        knowledge_block = ""
        if knowledge:
            knowledge_block = f"""
【内部知识参考（仅作业务规则提示，不可当 Schema）】
{knowledge}
说明: 可用于理解时间窗口、站点/渠道口径、业务筛选条件；禁止据此编造表或字段。
"""
        return f"""你是傲基（外贸家具）MySQL NL2SQL 助手。根据用户问题生成一条 SELECT。
只能查询: {", ".join(sorted(ALLOWED_TABLES))}
{SCHEMA_HINT}
{FEW_SHOT_EXAMPLES}
{metrics_block}{knowledge_block}硬性规则:
- 只返回一条 SQL，不要解释，不要 Markdown
- 金额优先 *_usd；时间用 order_date / snapshot_date / metric_date / spend_date
- 若上方给出指标口径，必须按口径选表/字段与公式，禁止自行换算口径
- 默认 LIMIT 50
- 不要编造不存在的表或字段

用户问题: {question}
"""

    def generate_sql(
        self,
        question: str,
        metric_context: str = "",
        knowledge_context: str = "",
    ) -> str:
        prompt = self._build_generate_prompt(
            question,
            metric_context=metric_context,
            knowledge_context=knowledge_context,
        )
        response = invoke_llm_with_retry(
            lambda: self.llm.invoke([SystemMessage(content=prompt)]),
            operation="nl2sql.generate",
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        return self.clean_sql(content)

    def repair_sql(
        self,
        question: str,
        sql: str,
        error: str,
        metric_context: str = "",
        knowledge_context: str = "",
    ) -> str:
        metrics_block = f"\n{metric_context}\n" if metric_context.strip() else ""
        knowledge = self._truncate_knowledge(knowledge_context)
        knowledge_block = f"\n{knowledge}\n" if knowledge else ""
        prompt = f"""上一条 SQL 执行失败，请修复为合法的单条 SELECT。
只能查询: {", ".join(sorted(ALLOWED_TABLES))}
{SCHEMA_HINT}
{metrics_block}{knowledge_block}规则: 只返回 SQL；保留原问题意图；遵守指标口径；默认 LIMIT 50；不可编造表/字段。

用户问题: {question}
原 SQL: {sql}
错误信息: {error}
"""
        response = invoke_llm_with_retry(
            lambda: self.llm.invoke([SystemMessage(content=prompt)]),
            operation="nl2sql.repair",
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        return self.clean_sql(content)

    def run(
        self,
        question: str,
        metric_context: str = "",
        knowledge_context: str = "",
    ) -> NL2SQLResult:
        """端到端：生成 → 校验 → 执行 →（失败则修复一次）."""
        result = NL2SQLResult(question=question)
        if metric_context.strip():
            result.meta["metric_context"] = metric_context
        if knowledge_context.strip():
            result.meta["knowledge_context"] = self._truncate_knowledge(knowledge_context)
        try:
            sql = self.generate_sql(
                question,
                metric_context=metric_context,
                knowledge_context=knowledge_context,
            )
            result.sql = sql
        except LLMRetryExhaustedError as exc:
            result.error = f"SQL 生成失败（重试耗尽）: {exc}"
            return result
        except Exception as exc:  # noqa: BLE001
            result.error = f"SQL 生成失败: {exc}"
            return result

        preview, rows = self.execute_sql(sql)
        if not preview.startswith("SQL 执行失败") and not preview.startswith("错误:"):
            result.success = True
            result.rows_preview = preview
            result.rows = rows
            result.meta["rows"] = rows
            return result

        # 自动修复一次
        result.error = preview
        try:
            repaired = self.repair_sql(
                question,
                sql,
                preview,
                metric_context=metric_context,
                knowledge_context=knowledge_context,
            )
            result.sql = repaired
            result.repaired = True
            preview2, rows2 = self.execute_sql(repaired)
            if not preview2.startswith("SQL 执行失败") and not preview2.startswith("错误:"):
                result.success = True
                result.rows_preview = preview2
                result.rows = rows2
                result.meta["rows"] = rows2
                result.error = None
                return result
            result.error = preview2
            result.rows_preview = preview2
        except LLMRetryExhaustedError as exc:
            result.error = f"SQL 修复失败（重试耗尽）: {exc}"
        except Exception as exc:  # noqa: BLE001
            result.error = f"SQL 修复失败: {exc}"

        return result


_nl2sql_skill: NL2SQLSkill | None = None


def get_nl2sql_skill() -> NL2SQLSkill:
    global _nl2sql_skill
    if _nl2sql_skill is None:
        _nl2sql_skill = NL2SQLSkill()
    return _nl2sql_skill
