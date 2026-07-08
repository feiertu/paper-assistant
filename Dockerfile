# ── Python Backend (前端在本地预构建，Docker 只负责 COPY) ──
FROM python:3.12-slim

WORKDIR /app

# 基础系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl gosu \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU（独立层缓存，几百 MB 不随 requirements.txt 变动重装）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Python 业务依赖
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt

# 编译完即删 build-essential，省 ~200MB
RUN apt-get remove -y build-essential && apt-get autoremove -y \
    && rm -rf /root/.cache

# 非 root 用户
RUN groupadd -r -g 1000 paper && useradd -r -g paper -d /app -u 1000 paper

# 后端代码
COPY --chown=paper:paper src/ ./src/
COPY --chown=paper:paper config.py .
COPY --chown=paper:paper entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 前端构建产物（本地预构建: cd frontend && npm run build）
COPY frontend/dist /app/static_dist

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
