#!/bin/bash
set -e

# ── 修复 volume 权限（volume 在运行时挂载，构建时 chown 无效） ──
chown -R paper:paper /app/data /app/logs 2>/dev/null || true

# 进程管理：trap 确保退出时清理所有子进程
cleanup() {
    echo "==> 收到退出信号，清理子进程…"
    jobs -p | xargs -r kill 2>/dev/null || true
    wait 2>/dev/null || true
    echo "==> 已退出"
}
trap cleanup SIGTERM SIGINT SIGQUIT

# ── FastAPI（降权到 paper 用户运行） ──
WORKERS=${UVICORN_WORKERS:-2}
echo "==> 启动 FastAPI on :8000 (workers=$WORKERS)"
gosu paper uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level info \
    --no-access-log &
FASTAPI_PID=$!

# ── Streamlit（降权到 paper 用户运行） ──
echo "==> 启动 Streamlit on :8501"
gosu paper streamlit run ui/app.py \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false &
STREAMLIT_PID=$!

# ── 监控子进程健康 ──
while kill -0 "$FASTAPI_PID" 2>/dev/null && kill -0 "$STREAMLIT_PID" 2>/dev/null; do
    sleep 5
done

echo "==> ⚠️ 子进程意外退出，容器将重启"
cleanup
exit 1
