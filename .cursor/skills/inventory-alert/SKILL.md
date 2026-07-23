---
name: au-agent-inventory-alert
description: >-
  傲基智能问答 Agent 的库存预警 Skill。当用户问低于安全库存、缺货/断货、补货建议、
  库龄过高/滞销、在途不足，或需要改预警规则、补货建议逻辑时使用。
---

# 傲基 Agent 库存预警 Skill

## 何时使用

- 「哪些 SKU 低于安全库存」
- 「US-CA-1 仓床类要补货吗」
- 「库龄 90 天以上有哪些」
- 调整预警规则 / 建议补货量算法

## 实现位置

- 核心：`app/agent/skills/inventory_alert.py`
- 接入：`retrieve_sql_context`（命中预警意图时优先于 NL2SQL）
- Tool：`inventory_alert_scan`

## 流程

1. 关键词判定是否为库存预警意图
2. 取最新 `inventory_snapshots` 快照
3. 规则扫描：
   - `below_safety`：可售 < 安全库存
   - `transit_gap`：缺口无法被在途覆盖
   - `aging_90`：库龄 90+ 偏高
4. 可选附带 operations 类 RAG 规范摘要
5. 写入结构化上下文供最终回答引用

## 口径

- 可售 = `available_qty`（不含 reserved / in_transit）
- 缺口 = `max(safety_stock - available_qty, 0)`

## 修改建议

- 改阈值：编辑 `_evaluate_row`
- 改意图词：编辑 `_ALERT_INTENT` / `_INVENTORY_CONTEXT`
- 与指标口径保持一致：可售不要改成 on_hand
