#!/bin/bash
set -e

WORKERS=${UVICORN_WORKERS:-2}
echo "==> Starting FastAPI on :8000 (workers=$WORKERS)"
uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --log-level info \
    --no-access-log &

echo "==> Starting Streamlit on :8501"
exec streamlit run ui/app.py \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false
