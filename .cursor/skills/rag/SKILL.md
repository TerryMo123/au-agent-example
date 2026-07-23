---
name: au-agent-rag
description: >-
  傲基智能问答 Agent 的 RAG / 知识检索 Skill。当用户问退货政策、合规、运营规范、广告管控、
  物流时效等内部制度，或需要改类目路由、召回/重排、引用溯源时使用。
---

# 傲基 Agent RAG Skill

## 何时使用

- 制度 / 流程 / 合规类问答（非结构化数字）
- 调整文档类目关键词、召回路数、重排权重
- 排查「答非所问 / 引用错文档 / 未带出处」

## 实现位置

- 类目规则：`app/agent/skills/rag_catalog.py`
- 核心：`app/agent/skills/rag.py`
- 接入节点：`retrieve_rag_context`
- Tool：`search_internal_knowledge`

## 流程

1. 关键词推断 `category`（policy / operations / ads …）
2. **多路召回**：全局向量 + 类目过滤向量
3. **轻量重排**：相关度 × 关键词重叠 × 类目加分
4. 写入 `rag_context`，结构化 `sources`（title / category / doc_id / snippet）

## 修改建议

- 新类目：在 `CATEGORY_ALIASES` 增加映射，并确保 ingest 时 metadata.category 一致
- 召回不够：调大 `top_k` 或 `fetch_multiplier`
- 类目误伤：删掉过短/过泛别名，优先长词
