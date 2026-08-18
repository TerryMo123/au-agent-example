# HTTPS 配置（moyong.net）

证书与 443 **已改到 `moyong-gateway`**，不要再给 `au-agent-web` 映射 80/443。

1. 把证书放到 `moyong-gateway/certs/`（`fullchain.pem` / `privkey.pem`）
2. ACME webroot 用 `moyong-gateway/certbot/www`（网关 Nginx 已有 `/.well-known/acme-challenge/`）
3. 在 `moyong-gateway/docker-compose.yml` 打开 `443:443` 并挂载 SSL 配置

申请证书示例（Let's Encrypt）：

```bash
cd /path/to/moyong-gateway
sudo certbot certonly --webroot \
  -w "$(pwd)/certbot/www" \
  -d moyong.net -d www.moyong.net \
  --email 你的邮箱@example.com \
  --agree-tos --no-eff-email
```

`.env.prod` 的 CORS 在启用 HTTPS 后改为：

```bash
CORS_ORIGINS=https://moyong.net,https://www.moyong.net
```
