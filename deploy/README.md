# 傲基 Agent 部署指南（Docker + Kubernetes）

本仓库已提供：

- 后端 `Dockerfile`
- 前端 `../au-agent-web-example/Dockerfile` + Nginx 反代 `/api`（含 SSE）
- `docker-compose.prod.yml`（先 Docker 验证）
- `deploy/k8s/*`（Namespace / ConfigMap / Secret / Redis / API / Web / HPA / Ingress）

## 架构建议

```
浏览器 → Ingress(TLS) → au-agent-web(×N)
                              └─ /api → au-agent-api(×1~N) → MySQL(外部)
                                                    ├→ Redis(PVC/缓存+限流)
                                                    └→ Chroma local PVC 或 Chroma Server
```

| 组件 | 是否可多副本 | 说明 |
|------|-------------|------|
| Web | 是 | 无状态，优先做负载均衡 |
| API | 视向量库而定 | `VECTOR_BACKEND=local` + RWO 时建议 **1 副本**；`http` 远程 Chroma 或 RWX 后可 HPA |
| Redis | 1（示例） | 语义缓存 + 限流；已用 PVC 持久化 AOF |
| Chroma | 1（Server） | `10-chroma.yaml`；API 无状态后可水平扩展 |
| MySQL | 外部 | 远端库，K8s 内只配连接信息 |

## 0. 前置条件

- Linux 服务器，Docker / containerd
- Kubernetes（kubeadm / k3s / ACK 等），已装 `kubectl`
- （推荐）Nginx Ingress Controller
- MySQL 已建库并完成 seed；容器能访问该 MySQL 地址
- 百炼 `OPENAI_API_KEY`

**安全：** 不要把 `.env` / `02-secret.yaml` 提交到 Git；若密钥曾出现在仓库或聊天中，建议轮换。

## 1. 先用 Docker Compose 验证（推荐）

在 **API 仓库根目录**：

```bash
cp .env.prod.example .env.prod
# 编辑 .env.prod：填 OPENAI_API_KEY、MYSQL_*（宿主机 MySQL 用 host 网络或宿主机内网 IP，不要写 127.0.0.1 除非用 host 模式）

# 若 MySQL 在宿主机：LINUX 可写 MYSQL_HOST=172.17.0.1 或真实内网 IP
docker compose -f docker-compose.prod.yml up -d --build

# 灌入向量库（首次）
docker compose -f docker-compose.prod.yml exec au-agent-api \
  python scripts/ingest_rag.py

# 浏览器打开 http://服务器IP:8080
curl -s http://127.0.0.1:8080/api/v1/health
```

## 2. 构建并推送镜像

```bash
chmod +x deploy/build-images.sh
export REGISTRY=你的仓库地址/命名空间   # 如 registry.cn-hangzhou.aliyuncs.com/yourns
export TAG=v0.1.0
PUSH=1 ./deploy/build-images.sh
```

单机无私有仓库时，可只 build，并在各节点 `docker load`，或 `imagePullPolicy: IfNotPresent` + 各节点已有镜像。

## 3. 部署到 Kubernetes

```bash
# 1) 改配置
cp deploy/k8s/02-secret.yaml.example deploy/k8s/02-secret.yaml
# 编辑 01-configmap.yaml 的 MYSQL_HOST 等
# 编辑 02-secret.yaml 的密钥
# 编辑 05-api.yaml / 07-web.yaml 的镜像名 YOUR_REGISTRY/...
# 编辑 08-ingress.yaml 的域名；无域名可先用 09-web-nodeport.yaml

# 2) 应用
kubectl apply -f deploy/k8s/00-namespace.yaml
kubectl apply -f deploy/k8s/01-configmap.yaml
kubectl apply -f deploy/k8s/02-secret.yaml
kubectl apply -f deploy/k8s/03-redis.yaml
kubectl apply -f deploy/k8s/04-api-pvc.yaml
kubectl apply -f deploy/k8s/05-api.yaml
kubectl apply -f deploy/k8s/07-web.yaml
kubectl apply -f deploy/k8s/08-ingress.yaml
# 或: kubectl apply -f deploy/k8s/09-web-nodeport.yaml

# 3) 等 Ready
kubectl -n au-agent get pods,svc,ingress

# 4) 首次灌 RAG（有文档时）
kubectl -n au-agent exec -it deploy/au-agent-api -- python scripts/ingest_rag.py
```

访问：

- Ingress：`http://au-agent.example.com`（DNS 指到 Ingress）
- NodePort：`http://任意节点IP:30080`

## 4. 负载均衡 / 水平扩展 / TLS

1. **入口层**：Ingress Controller 对 `au-agent-web` 做多 Pod 轮询。
2. **默认 API**：本地 Chroma + RWO PVC → `replicas: 1`（`05-api.yaml`）。
3. **推荐扩 API（无状态）**：
   ```bash
   kubectl apply -f deploy/k8s/10-chroma.yaml
   # ConfigMap 设 VECTOR_BACKEND=http, CHROMA_HOST=au-agent-chroma
   kubectl apply -f deploy/k8s/05-api-stateless.yaml
   kubectl apply -f deploy/k8s/06-api-hpa.yaml
   ```
4. **Docker Compose 无状态验证**：
   ```bash
   docker compose -f docker-compose.prod.yml -f docker-compose.chroma.yml up -d --build
   ```
5. **HTTPS**：使用 `08-ingress-tls.yaml`（需 cert-manager + ClusterIssuer），或在 `08-ingress.yaml` 填入已有 TLS Secret。
6. **限流**：ConfigMap / `.env.prod` 中 `RATE_LIMIT_ENABLED=true`（按用户 + IP，优先 Redis）。
7. **SSE**：Ingress / Nginx 已关缓冲、超时 3600s。

## 5. 运维常用命令

```bash
kubectl -n au-agent logs -f deploy/au-agent-api
kubectl -n au-agent rollout restart deploy/au-agent-api
kubectl -n au-agent describe pvc au-agent-redis au-agent-chroma au-agent-chroma-server
kubectl -n au-agent top pods   # 需 metrics-server
curl -s http://127.0.0.1:8000/api/v1/ready
curl -s http://127.0.0.1:8000/metrics | head
```

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| API 连不上 MySQL | 检查安全组/防火墙；容器里 `MYSQL_HOST` 不能用仅本机监听的 `127.0.0.1` |
| Pod Pending（PVC） | 确认集群有默认 StorageClass |
| 聊天无流式输出 | 确认走的是 Web 的 `/api` 反代，且 Ingress 关闭了 proxy-buffering |
| 知识库空 | 在 API Pod 内执行 `scripts/ingest_rag.py` |
| 多 API 副本异常 | 本地 Chroma RWO 不支持多挂；改 `VECTOR_BACKEND=http` + `10-chroma.yaml` |
| 429 过多 | 调大 `RATE_LIMIT_CHAT_PER_MINUTE` / `RATE_LIMIT_IP_PER_MINUTE` |
| Redis 重启丢缓存 | 已改 PVC（`03-redis.yaml`）；勿用 emptyDir |

## 7. 推荐上线顺序

1. Compose 在单机跑通（健康检查 + 一次完整问答）
2. 镜像推仓库 → K8s 单副本 API + 双副本 Web + NodePort
3. 配 Ingress / 域名 / HTTPS（`08-ingress-tls.yaml`）
4. 开语义缓存 Redis + 限流，观察资源
5. 切远程 Chroma → 无状态 API → 启用 HPA
