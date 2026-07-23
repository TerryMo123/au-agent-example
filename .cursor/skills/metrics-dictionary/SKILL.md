---
name: au-agent-metrics-dictionary
description: >-
  傲基智能问答 Agent 的指标口径 Skill。当用户问 GMV、可售库存、ACOS、退货率、ROAS、
  转化率、毛利等业务指标定义/算法，或需要修改口径目录、别名、SQL 提示时使用。
---

# 傲基 Agent 指标口径 Skill

## 何时使用

- 统一业务指标定义（避免同词不同算法）
- 调整口径别名、公式、推荐表字段
- 排查「问的是可售却查了在库」「GMV 乱算」等问题

## 实现位置

- 目录：`app/agent/skills/metrics_catalog.py`
- 核心：`app/agent/skills/metrics_dictionary.py`
- 接入：`retrieve_sql_context` 先 `resolve` 再调用 NL2SQL
- Tool：`resolve_business_metrics`

## 流程

1. 用别名/关键词匹配问题中的指标（确定性，无 LLM）
2. 输出标准定义 + 公式 + SQL 提示
3. 注入 NL2SQL 生成/修复提示词
4. 同时写入 Agent 状态 `metrics_context`，供最终回答引用

## 修改建议

- 新增指标：在 `METRIC_CATALOG` 增加 `MetricDef`（key、aliases、formula、sql_hint）
- 别名冲突：长别名优先匹配；英文别名走词边界
- 口径变更后建议同步检查 `schema.py` Few-shot 是否一致
