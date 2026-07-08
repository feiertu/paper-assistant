#!/bin/bash
# Paper Assistant 一键入库修复部署脚本
# 用法: ssh root@47.86.236.212 "bash -s" < scripts/deploy_fixes.sh
set -e

cd /opt/paper-assistant

echo "========================================="
echo "  Paper Assistant 修复部署"
echo "========================================="

# ── 1. 更新 docker-compose.yml ──
echo "[1/5] 更新 docker-compose.yml..."
cat > docker-compose.yml << 'DOCKER_EOF'
version: '3.8'

services:
  paper-assistant:
    build: .
    container_name: paper-assistant
    expose:
      - "8000"
    volumes:
      - paper_data:/app/data
      - paper_logs:/app/logs
      - paper_static:/app/static
      - certbot_www:/var/www/certbot:ro
    env_file:
      - .env
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 3G
        reservations:
          cpus: '0.5'
          memory: 512M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  nginx:
    image: nginx:stable-alpine
    container_name: paper-nginx
    ports:
      - "80:80"
      - "443:443"
    environment:
      - API_AUTH_KEY=${API_AUTH_KEY:-}
    volumes:
      - paper_static:/usr/share/nginx/html:ro
      - ./nginx/paper-assistant.conf.template:/etc/nginx/templates/default.conf.template:ro
      - certbot_certs:/etc/letsencrypt:ro
      - certbot_www:/var/www/certbot:ro
      - ./nginx/options-ssl-nginx.conf:/etc/nginx/options-ssl-nginx.conf:ro
    depends_on:
      paper-assistant:
        condition: service_healthy
    restart: unless-stopped

  certbot:
    image: certbot/certbot:latest
    container_name: paper-certbot
    volumes:
      - certbot_certs:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew --webroot -w /var/www/certbot --quiet; sleep 12h; done'"
    restart: unless-stopped

networks:
  default:
    name: paper-assistant_default

volumes:
  paper_data:
    driver: local
  paper_logs:
    driver: local
  paper_static:
    driver: local
  certbot_certs:
    driver: local
  certbot_www:
    driver: local
DOCKER_EOF

# ── 2. 更新 entrypoint.sh ──
echo "[2/5] 更新 entrypoint.sh..."
cat > entrypoint.sh << 'ENTRY_EOF'
#!/bin/bash
set -e

# Fix volume permissions
chown -R paper:paper /app/data /app/logs /app/.cache /app/static 2>/dev/null || true

# HuggingFace cache dir (for sentence-transformers local model)
export HF_HOME=/app/.cache/huggingface
export HOME=/app

# Process management
cleanup() {
    echo "==> Received exit signal, cleaning up..."
    jobs -p | xargs -r kill 2>/dev/null || true
    wait 2>/dev/null || true
    echo "==> Exited"
}
trap cleanup SIGTERM SIGINT SIGQUIT

# FastAPI (Vue SPA served by nginx, API only)
WORKERS=${UVICORN_WORKERS:-1}
echo "==> Starting Paper Assistant API on :8000 (workers=$WORKERS)"
exec gosu paper uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level info \
    --no-access-log
ENTRY_EOF
chmod +x entrypoint.sh

# ── 3. 创建 nginx 模板（注入 API Key） ──
echo "[3/5] 创建 nginx 模板..."
. .env 2>/dev/null || true
cat > nginx/paper-assistant.conf.template << 'NGINX_EOF'
# HTTP -> HTTPS + ACME
server {
    listen 80;
    server_name feiertu.xyz www.feiertu.xyz;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS
server {
    listen 443 ssl http2;
    server_name feiertu.xyz www.feiertu.xyz;
    ssl_certificate     /etc/letsencrypt/live/feiertu.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/feiertu.xyz/privkey.pem;
    include             /etc/nginx/options-ssl-nginx.conf;
    client_max_body_size 100M;

    # Vue SPA static assets (long cache)
    location /assets/ {
        root /usr/share/nginx/html;
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }
    location /favicon.svg {
        root /usr/share/nginx/html;
        expires 1y;
    }

    # Vue SPA - all non-/api routes fallback to index.html
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    }

    # SSE streaming endpoints (must be before /api/, buffering disabled)
    location /api/rag/query/stream {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://paper-assistant:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-API-Key ${API_AUTH_KEY};
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
        chunked_transfer_encoding off;
    }
    location /api/agent/query/stream {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://paper-assistant:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-API-Key ${API_AUTH_KEY};
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
        chunked_transfer_encoding off;
    }

    # General API proxy
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://paper-assistant:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-API-Key ${API_AUTH_KEY};
        proxy_read_timeout 600s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 600s;
    }
}
NGINX_EOF

# ── 4. 更新 main.py (embedding preload) ──
echo "[4/5] 更新 src/api/main.py..."
python3 -c "
import re
with open('src/api/main.py', 'r') as f:
    content = f.read()

# Check if preload already exists
if '_preload_embedding_model' not in content:
    # Insert after _validate_config_on_startup()
    old = '''_validate_config_on_startup()

# ── App 实例 ──'''
    new = '''_validate_config_on_startup()


def _preload_embedding_model() -> None:
    \"\"\"Preload embedding model to avoid cold start on first ingest.\"\"\"
    from src.logging_config import get_logger
    _log = get_logger(__name__)
    if 'local' in config.EMBEDDING_PROVIDER:
        try:
            _log.info('Preloading local embedding model...')
            from src.embed import get_embedder
            embedder = get_embedder()
            _log.info('Embedding model preloaded: providers=%s dim=%d',
                      embedder.providers, embedder.dim)
        except Exception as e:
            _log.warning('Embedding preload failed (will load on first use): %s', e)


_preload_embedding_model()

# ── App 实例 ──'''
    content = content.replace(old, new)
    with open('src/api/main.py', 'w') as f:
        f.write(content)
    print('main.py updated')
else:
    print('main.py already has preload - skipping')
"

# ── 5. 更新 Dockerfile (HOME env) ──
echo "[5/5] 更新 Dockerfile..."
python3 -c "
with open('Dockerfile', 'r') as f:
    content = f.read()
if 'HOME=/app' not in content:
    content = content.replace(
        'ENV HF_HOME=/app/.cache/huggingface',
        'ENV HF_HOME=/app/.cache/huggingface \\\n    HOME=/app'
    )
    with open('Dockerfile', 'w') as f:
        f.write(content)
    print('Dockerfile updated')
else:
    print('Dockerfile already has HOME - skipping')
"

# ── 6. 重建并重启 ──
echo ""
echo "========================================="
echo "  Rebuilding & restarting containers..."
echo "========================================="
docker compose down
docker compose build --no-cache paper-assistant
docker compose up -d

echo ""
echo "========================================="
echo "  Waiting for services to be ready..."
echo "========================================="
sleep 15

# Health check
echo ""
echo "Health check:"
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "API not ready yet"

echo ""
echo "Nginx config test:"
docker exec paper-nginx nginx -t 2>&1 || true

echo ""
echo "========================================="
echo "  Deployment complete!"
echo "========================================="
echo ""
echo "Please test: https://feiertu.xyz"
echo "Check logs: docker compose logs -f paper-assistant"
