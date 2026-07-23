# 傲基智能数据问答 Agent

面向外贸家具（傲基 / AoJi）场景的企业级智能问答后端示例：用自然语言查询经营数据、检索内部制度，并给出库存预警、广告诊断、退货归因等专项分析。

配套前端仓库：[`au-agent-web-example`](../au-agent-web-example)（React + Ant Design + AntV，SSE 流式对话与数据看板）。

---

## 功能概览

| 能力 | 说明 |
|------|------|
| **NL2SQL** | 自然语言 → 只读 SQL → MySQL 查询，结果可表格/曲线展示 |
| **RAG** | Chroma 向量检索内部政策、运营规范、合规文档等 |
| **指标口径** | GMV / ACOS / 可售库存等指标定义与别名对齐 |
| **库存预警** | 低于安全库存、高库龄、在途缺口与补货建议 |
| **广告诊断** | ACOS/ROAS 超标扫描、降出价与否定词建议 |
| **退货归因** | 原因码分布、业务归因与处置建议 |
| **智能路由** | 规则优先 + 小模型兜底（`sql` / `rag` / `hybrid`） |
| **语义缓存** | 可选 Redis：精确匹配 + 向量近邻复用历史答案 |
| **会话管理** | MySQL 持久化多轮会话与消息 |
| **数据 API** | 产品 / 订单 / 库存 / 退货 / 广告 / 生命周期等列表接口 |

---

## 技术栈

- **API**：FastAPI + Uvicorn
- **Agent**：LangGraph + LangChain
- **模型**：阿里云百炼（OpenAI 兼容，默认 `qwen-max` / 路由 `qwen-turbo` / `text-embedding-v3`）
- **数据**：MySQL 8 + SQLAlchemy
- **向量库**：Chroma
- **缓存**：Redis（可选）
- **部署**：Docker / Docker Compose / Kubernetes（见 [`deploy/README.md`](./deploy/README.md)）

---

## 架构简述

```
用户问题
   │
   ▼
规则优先路由（模糊时 qwen-turbo）
   │
   ├─ sql ──────► 指标口径 → 专项 Skill / NL2SQL → MySQL
   ├─ rag ──────► Chroma 知识检索
   └─ hybrid ───► SQL 与 RAG 并行，RAG 知识注入 NL2SQL
   │
   ▼
流式生成回答（SSE）+ 可视化规格 + 引用溯源
```

Agent 图节点：`route → retrieve_sql / retrieve_rag →（hybrid 时 enrich）→ generate`。

---

## 目录结构

```
au-agent-example/
├── app/
│   ├── agent/           # LangGraph、路由、Skills、可视化
│   ├── api/routes/      # chat / sessions / data / health
│   ├── db/              # MySQL 模型与连接
│   ├── services/        # 会话、问答、语义缓存、数据查询
│   ├── vector/          # Chroma
│   └── main.py
├── scripts/
│   ├── seed_mysql.py    # 演示业务数据灌库
│   └── ingest_rag.py    # 内部文档 → 向量库
├── deploy/              # Docker / K8s 部署说明与清单
├── docker-compose.yml   # 本地 MySQL（可选）
├── docker-compose.prod.yml
├── Dockerfile
├── requirements.txt
└── run.py
```

---

## 快速开始

### 1. 环境要求

- Python 3.12+
- MySQL 8
- （可选）Redis
- 阿里云百炼 API Key

### 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env：填写 OPENAI_API_KEY、MYSQL_* 等
```

### 4. 准备数据库

```bash
# 可选：本仓库自带 MySQL Compose
docker compose up -d

# 建表 + 灌入演示数据（按需加 --force）
.venv/bin/python scripts/seed_mysql.py

# 灌入 RAG 演示文档
.venv/bin/python scripts/ingest_rag.py
```

### 5. 启动 API

```bash
.venv/bin/python run.py
# http://127.0.0.1:8000
# 健康检查: GET /api/v1/health
# OpenAPI:   http://127.0.0.1:8000/docs
```

### 6. 启动前端（可选）

```bash
cd ../au-agent-web-example
npm install
npm run dev
# http://127.0.0.1:5173  （/api 代理到 8000）
```

---

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/chat` | 同步问答 |
| `POST` | `/api/v1/chat/stream` | SSE 流式问答 |
| `*` | `/api/v1/sessions...` | 会话列表 / 详情 / 创建 / 删除 |
| `GET` | `/api/v1/data/*` | 经营数据分页查询（产品、订单、库存等） |

流式事件类型：`status`（路由/检索阶段）、`token`（增量文本）、`done`（完整答案与 metadata）、`error`。

---

## Agent Skills

业务能力以 Skill 形式组织，Cursor 侧说明见 `.cursor/skills/*/SKILL.md`：

| Skill | 触发场景 |
|-------|----------|
| `metrics-dictionary` | 指标定义 / 口径 / 别名 |
| `nl2sql` | 销量、订单、GMV 等结构化查询 |
| `rag` | 政策、规范、合规等制度问答 |
| `inventory-alert` | 低库存、断货、库龄、补货 |
| `ad-diagnosis` | ACOS 超标、广告浪费、降出价 |
| `return-attribution` | 退货原因分布与归因建议 |

---

## 配置说明（节选）

| 变量 | 含义 | 默认 |
|------|------|------|
| `OPENAI_API_KEY` | 百炼 Key | — |
| `OPENAI_MODEL` | 主回答模型 | `qwen-max` |
| `OPENAI_ROUTER_MODEL` | 路由小模型 | `qwen-turbo` |
| `MYSQL_*` | 数据库连接 | 见 `.env.example` |
| `CHROMA_PERSIST_DIR` | 向量库目录 | `./data/chroma` |
| `SEMANTIC_CACHE_ENABLED` | 开启语义缓存 | `false` |
| `REDIS_URL` | Redis 地址 | `redis://127.0.0.1:6379/0` |

完整示例见 [`.env.example`](./.env.example)。**请勿将 `.env` 提交到 Git。**

---

## 部署

生产向 Docker 与 Kubernetes（Ingress / HPA / Redis / PVC）清单与步骤：

👉 **[`deploy/README.md`](./deploy/README.md)**

简要流程：

1. `docker compose -f docker-compose.prod.yml up -d --build` 单机验证  
2. `PUSH=1 REGISTRY=... ./deploy/build-images.sh` 构建推送  
3. `kubectl apply -f deploy/k8s/...` 上集群  

说明：本地 Chroma + RWO 卷时 API 建议单副本；Web 可多副本做负载均衡。

---

## 示例问题

- 近 7 天 Amazon US 的 GMV 是多少？
- 哪些 SKU 可售库存低于安全库存？
- 近 30 天广告 ACOS 超标的投放有哪些？
- 为什么某产品退货率上升？
- 退货政策是什么？

---

## 许可证

示例项目，仅供学习与内部演示；对外分发请自行补充 License 与合规要求。
