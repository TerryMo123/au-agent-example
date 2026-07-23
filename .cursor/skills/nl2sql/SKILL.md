---
name: au-agent-nl2sql
description: >-
  傲基智能问答 Agent 的 NL2SQL Skill。当用户询问销量、库存、订单、退货、广告 ACOS、
  GMV、采购、物流等结构化业务数据，或需要修改/调试 Text-to-SQL、表白名单、SQL 安全校验时使用。
---

# 傲基 Agent NL2SQL Skill

## 何时使用

- 自然语言查 MySQL 业务数据（NL2SQL）
- 调整 SQL 生成提示、Few-shot、白名单表
- 排查「SQL 执行失败 / 危险关键字 / 跨表错误」

## 实现位置

- 核心：`app/agent/skills/nl2sql.py`
- Schema：`app/agent/skills/schema.py`
- 接入节点：`app/agent/nodes/executor.py` → `retrieve_sql_context`
- Tool 入口：`nl2sql_query` / `query_structured_data`（`app/agent/tools/__init__.py`）

## 流程

1. **指标口径 Skill** 先解析问题中的业务指标（GMV/可售/ACOS 等）
2. LLM 根据 Schema + Few-shot + **口径约束**（hybrid 时另附 RAG 知识参考）生成单条 `SELECT`
3. `validate_sql`：只读、禁多语句、表白名单
4. 执行；失败则带错误信息 **自动修复一次**（仍带口径 / 知识）
5. 结果写入 Agent 状态 `sql_result`，口径写入 `metrics_context`

## hybrid 编排

- `retrieve_sql`（专项 Skill，暂缓 NL2SQL）与 `retrieve_rag` **并行**
- 汇合后 `enrich_sql_with_rag`：把 `rag_context` 注入 `knowledge_context` 再跑 NL2SQL
- RAG 文本仅作业务规则提示（时间窗/站点口径等），禁止当 Schema 编造字段

## 安全硬约束

- 仅 `SELECT`
- 禁止 insert/update/delete/drop/alter/truncate/create 等
- 仅允许 `ALLOWED_TABLES` 中的表
- LLM 瞬时错误走 `app/llm_retry.py`（最多 3 次）后降级

## 修改建议

- 加表/字段：先改 `schema.py` 的 `ALLOWED_TABLES` 与 `SCHEMA_HINT`，再补 Few-shot
- 提升准确率：优先改 `metrics_catalog.py` 口径，再补 Few-shot；不要放宽安全校验
- 口径 Skill 文档：`.cursor/skills/metrics-dictionary/SKILL.md`
- 产品全链路状态：优先 `lifecycle_events`，用 `batch_no` 关联 `sku_batches` / 采购 / 头程 / 库存 / 订单