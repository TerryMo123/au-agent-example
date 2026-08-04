# 经营数据 Agent · HTTPS 配置说明（moyong.net）

目标：`https://moyong.net` 可访问，HTTP 自动跳转 HTTPS。

## 0. 前置

- 域名已解析到服务器公网 IP（`@` / `www` 的 A 记录）
- 安全组已放行 **TCP 80**、**TCP 443**
- Compose 中 `au-agent-web` 已映射 `80:80`（当前仓库已是）

## 1. 申请证书（二选一）

### 方式 A：阿里云免费 DV 证书（国内推荐）

1. 打开 [数字证书管理服务](https://yundun.console.aliyun.com/) → SSL 证书 → 免费证书 → 创建
2. 绑定域名：`moyong.net`（如需 www，再申请一张或选「含 www」）
3. 按提示做 **DNS 验证**（在云解析加 TXT）
4. 签发后下载 **Nginx** 格式
5. 解压后放到服务器项目目录：

```bash
mkdir -p deploy/certs
# 将下载的 pem 改名为：
#   deploy/certs/fullchain.pem   （证书链，有的包叫 xxx.pem）
#   deploy/certs/privkey.pem     （私钥，有的包叫 xxx.key）
ls -l deploy/certs/
```

### 方式 B：Let's Encrypt（certbot）

服务器上（需已安装 certbot）：

```bash
cd /path/to/au-agent-example
mkdir -p deploy/certbot/www deploy/certs

# 确保当前仍用 HTTP 配置，且 80 由 au-agent-web 占用
docker compose -f docker-compose.prod.yml up -d au-agent-web

sudo certbot certonly --webroot \
  -w "$(pwd)/deploy/certbot/www" \
  -d moyong.net -d www.moyong.net \
  --email 你的邮箱@example.com \
  --agree-tos --no-eff-email

# 拷贝到挂载目录
sudo cp /etc/letsencrypt/live/moyong.net/fullchain.pem deploy/certs/
sudo cp /etc/letsencrypt/live/moyong.net/privkey.pem deploy/certs/
sudo chown "$USER":"$USER" deploy/certs/*.pem
```

> webroot 要求 Nginx 已配置 `/.well-known/acme-challenge/`（本仓库 `nginx-web.conf` 已包含）。

## 2. 启用 HTTPS（改 Compose 挂载）

编辑 `docker-compose.prod.yml` 中 `au-agent-web`：

```yaml
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/nginx-web-ssl.conf:/etc/nginx/conf.d/default.conf:ro
      - ./deploy/certs:/etc/nginx/certs:ro
      - ./deploy/certbot/www:/var/www/certbot:ro
```

然后：

```bash
docker compose -f docker-compose.prod.yml up -d au-agent-web
docker compose -f docker-compose.prod.yml exec au-agent-web nginx -t
curl -I http://moyong.net          # 应 301 到 https
curl -I https://moyong.net         # 应 200
```

## 3. 改后端 CORS

`.env.prod` 中：

```bash
CORS_ORIGINS=https://moyong.net,https://www.moyong.net
```

重启 API：

```bash
docker compose -f docker-compose.prod.yml up -d au-agent-api
```

## 4. 续期

- **阿里云证书**：到期前在控制台重新申请/替换 `deploy/certs/` 内文件，再 `up -d au-agent-web`
- **Let's Encrypt**：cron 续期后重新 `cp` 到 `deploy/certs/` 并执行  
  `docker compose -f docker-compose.prod.yml exec au-agent-web nginx -s reload`
