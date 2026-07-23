---
name: au-agent-return-attribution
description: >-
  傲基智能问答 Agent 的退货归因 Skill。当用户问退货原因分布、破损是否偏高、退货归因、
  售后主因分析，或需要调整原因码映射 / 归因建议时使用。
---

# 傲基 Agent 退货归因 Skill

## 何时使用

- 「近 30 天退货原因分布」
- 「破损退货是否偏高，是不是头程问题」
- 「床类退货归因」
- 调整 `reason_code` → 归因/建议映射

## 实现位置

- 核心：`app/agent/skills/return_attribution.py`
- 接入：`retrieve_sql_context`
- Tool：`return_attribution_scan`

## 流程

1. 关键词判定退货归因意图
2. 聚合 `returns`（按 `opened_date`、`reason_code`）
3. 输出原因占比 + 归因方向 + 处置建议
4. 附带退款金额 Top SKU 与主因
5. 可选检索 policy / logistics / product 规范

## 原因码映射（Demo）

| reason_code | 归因方向 |
|-------------|---------|
| damaged | 物流/包装 |
| size_issue / not_as_described | Listing |
| missing_parts | 工厂装箱/质检 |
| quality | 品质/质检 |
| changed_mind | 买家原因（政策内） |

## 修改建议

- 新原因码：更新 `REASON_META`
- 改意图词：`_ATTR_INTENT` / `_RETURN_CONTEXT`
- 破损偏高阈值：`_build_highlights`
