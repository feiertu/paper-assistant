#!/bin/bash
set -e

# ── 修复 volume 权限 ──
chown -R paper:paper /app/data /app/logs /app/.cache /app/static 2>/dev/null || true

# HuggingFace 缓存目录（sentence-transformers 本地模型）
export HF_HOME=/app/.cache/huggingface
export HOME=/app

# 进程管理
cleanup() {
    echo "==> 收到退出信号，清理子进程…"
    jobs -p | xargs -r kill 2>/dev/null || true
    wait 2>/dev/null || true
    echo "==> 已退出"
}
trap cleanup SIGTERM SIGINT SIGQUIT

# ── FastAPI（Vue SPA 由 nginx 直接 serve，这里只启动 API） ──
WORKERS=${UVICORN_WORKERS:-1}
echo "==> 启动 Paper Assistant API on :8000 (workers=$WORKERS)"
exec gosu paper uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level info \
    --no-access-log
