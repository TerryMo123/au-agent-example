#!/usr/bin/env bash
# 在服务器上构建并推送镜像（按需修改 REGISTRY）
set -euo pipefail

ROOT_API="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_WEB="$(cd "$ROOT_API/../au-agent-web-example" && pwd)"
REGISTRY="${REGISTRY:-YOUR_REGISTRY}"
TAG="${TAG:-latest}"

echo "==> build api -> ${REGISTRY}/au-agent-api:${TAG}"
docker build -t "${REGISTRY}/au-agent-api:${TAG}" "$ROOT_API"

echo "==> build web -> ${REGISTRY}/au-agent-web:${TAG}"
docker build -t "${REGISTRY}/au-agent-web:${TAG}" "$ROOT_WEB"

if [[ "${PUSH:-0}" == "1" ]]; then
  docker push "${REGISTRY}/au-agent-api:${TAG}"
  docker push "${REGISTRY}/au-agent-web:${TAG}"
fi

echo "done. 请将 deploy/k8s 中 YOUR_REGISTRY 替换为: ${REGISTRY}"
