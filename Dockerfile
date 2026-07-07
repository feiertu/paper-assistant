FROM python:3.12-slim

WORKDIR /app

# 系统依赖（PyMuPDF + gosu 用于运行时降权）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户（固定 UID=1000 避免 volume 权限漂移）
RUN groupadd -r -g 1000 paper && useradd -r -g paper -d /app -u 1000 paper

# Python 依赖 — 先安装 CPU 版 PyTorch 避免拉入 CUDA/nvidia 包（~3GB）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY --chown=paper:paper . .

# 数据目录（挂载点）+ HuggingFace 缓存
RUN mkdir -p /app/data/parsed /app/data/chroma_db /app/data/raw \
    /app/data/processed /app/logs /app/data/chroma_backup \
    /app/.cache/huggingface \
    && chown -R paper:paper /app/data /app/logs /app/.cache

ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000 8501

COPY --chown=paper:paper entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
