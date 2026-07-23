---
name: au-agent-ad-diagnosis
description: >-
  傲基智能问答 Agent 的广告诊断 Skill。当用户问 ACOS/ROAS 是否超标、广告浪费、降出价、
  否定关键词、投放诊断，或需要调整目标 ACOS / 诊断规则时使用。
---

# 傲基 Agent 广告诊断 Skill

## 何时使用

- 「床类 ACOS 是否超标」
- 「近 7 天广告诊断」
- 「哪些投放该降出价」
- 调整目标 ACOS、严重倍数、建议文案

## 实现位置

- 核心：`app/agent/skills/ad_diagnosis.py`
- 接入：`retrieve_sql_context`（与库存预警并列的规则 Skill）
- Tool：`ad_diagnosis_scan`

## 流程

1. 关键词判定广告诊断意图
2. 聚合 `ad_spend_daily` 近 N 天（默认 7）花费与广告销售
3. 规则：
   - `spend_no_sales`：有花费无广告销售
   - `acos_critical`：ACOS > 目标 × 1.5 → 降出价 10%
   - `acos_over_target`：ACOS > 目标 → 收紧投放
4. 可选附带 ads 类 RAG 规范
5. 写入【广告诊断】上下文

## 口径与目标

- ACOS = SUM(spend_usd) / SUM(ad_sales_usd)（比率）
- 床类目标 ≤ 25%；床头柜 ≤ 30%

## 修改建议

- 改目标：`TARGET_ACOS_BY_CATEGORY`
- 改意图词：`_DIAG_INTENT` / `_AD_CONTEXT`
- 与指标口径 Skill 的 ACOS 定义保持一致
