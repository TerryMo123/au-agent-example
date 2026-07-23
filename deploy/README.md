# 傲基 Agent 部署指南（Docker + Kubernetes）

本仓库已提供：

- 后端 `Dockerfile`
- 前端 `../au-agent-web-example/Dockerfile` + Nginx 反代 `/api`（含 SSE）
- `docker-compose.prod.yml`（先 Docker 验证）
- `deploy/k8s/*`（Namespace / ConfigMap / Secret / Redis / API / Web / HPA / Ingress）

## 架构建议

```
浏览器 → Ingress/NodePort → au-agent-web(×N, HPA)
                              └─ /api → au-agent-api(×1~N) → MySQL(外部)
                                                    ├→ Redis(缓存)
                                                    └→ Chroma PVC
```

| 组件 | 是否可多副本 | 说明 |
|------|-------------|------|
| Web | 是 | 无状态，优先做负载均衡 |
| API | 视 Chroma 而定 | 本地 Chroma + RWO PVC 时建议 **1 副本**；有 NFS/RWX 或外部向量库后再水平扩展 |
| Redis | 1（示例） | 语义缓存共享；生产可换云 Redis |
| MySQL | 外部 | 你当前已有远端库，K8s 内只配连接信息 |

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

## 4. 负载均衡怎么落地

1. **入口层**：Ingress Controller 对 `au-agent-web` 做多 Pod 轮询（已配 HPA min=2）。
2. **应用层**：Web → Service `au-agent-api`；当前 API `replicas: 1`，避免 RWO Chroma 多挂载冲突。
3. **扩 API**：把 PVC 换成 **ReadWriteMany**，`05-api.yaml` 里 `replicas` 调高、`strategy` 改为 `RollingUpdate`，再启用 `06-api-hpa.yaml`。
4. **SSE**：Ingress / Nginx 已关缓冲、超时 3600s，避免流式对话被截断。

## 5. 运维常用命令

```bash
kubectl -n au-agent logs -f deploy/au-agent-api
kubectl -n au-agent rollout restart deploy/au-agent-api
kubectl -n au-agent describe pvc au-agent-chroma
kubectl -n au-agent top pods   # 需 metrics-server
```

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| API 连不上 MySQL | 检查安全组/防火墙；容器里 `MYSQL_HOST` 不能用仅本机监听的 `127.0.0.1` |
| Pod Pending（PVC） | 确认集群有默认 StorageClass |
| 聊天无流式输出 | 确认走的是 Web 的 `/api` 反代，且 Ingress 关闭了 proxy-buffering |
| 知识库空 | 在 API Pod 内执行 `scripts/ingest_rag.py` |
| 多 API 副本异常 | Chroma RWO 不支持多挂，保持 1 副本或换 RWX |

## 7. 推荐上线顺序

1. Compose 在单机跑通（健康检查 + 一次完整问答）
2. 镜像推仓库 → K8s 单副本 API + 双副本 Web + NodePort
3. 配 Ingress / 域名 / HTTPS
4. 开语义缓存 Redis，观察资源后再考虑 API 水平扩展
