#!/bin/bash
set -e

echo "==> Starting FastAPI on :8000"
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &

echo "==> Starting Streamlit on :8501"
exec streamlit run ui/app.py \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false
