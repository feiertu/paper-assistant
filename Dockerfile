# ── Stage 1: Build Vue Frontend ──
FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python Backend ──
FROM python:3.12-slim

WORKDIR /app

# 系统依赖（PyMuPDF + gosu + curl healthcheck）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r -g 1000 paper && useradd -r -g paper -d /app -u 1000 paper

# Python 依赖 — CPU 版 PyTorch
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码
COPY --chown=paper:paper src/ ./src/
COPY --chown=paper:paper config.py .
COPY --chown=paper:paper entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 前端构建产物 — 先放入暂存目录，启动时由 entrypoint 同步到 volume
COPY --from=frontend-builder /frontend/dist /app/static_dist

# 数据目录
RUN mkdir -p /app/data/parsed /app/data/chroma_db /app/data/raw \
    /app/data/processed /app/logs /app/data/chroma_backup \
    /app/.cache/huggingface \
    && chown -R paper:paper /app/data /app/logs /app/.cache /app/static_dist

ENV HF_HOME=/app/.cache/huggingface \
    HOME=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
