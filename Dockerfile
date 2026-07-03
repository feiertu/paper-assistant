FROM python:3.11-slim

WORKDIR /app

# 系统依赖（PyMuPDF 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r paper && useradd -r -g paper -d /app paper

# Python 依赖
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# 项目代码
COPY --chown=paper:paper . .

# 数据目录（挂载点）
RUN mkdir -p /app/data/parsed /app/data/chroma_db /app/data/raw \
    /app/data/processed /app/logs /app/data/chroma_backup \
    && chown -R paper:paper /app/data /app/logs

EXPOSE 8000 8501

COPY --chown=paper:paper entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 切换到非 root 用户
USER paper

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
