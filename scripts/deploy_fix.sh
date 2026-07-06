#!/bin/bash
# Deploy paper processing fixes to server
set -e

SERVER="root@47.86.236.212"
TARGET="/opt/paper-assistant"

echo "=== Copying fixed files to server ==="
scp src/api/main.py ${SERVER}:${TARGET}/src/api/main.py
scp src/fetch/arxiv.py ${SERVER}:${TARGET}/src/fetch/arxiv.py
scp src/db/dao.py ${SERVER}:${TARGET}/src/db/dao.py
scp src/embed/embedding.py ${SERVER}:${TARGET}/src/embed/embedding.py

echo "=== Rebuilding Docker container ==="
ssh ${SERVER} "cd ${TARGET} && docker compose up -d --build"

echo "=== Done ==="
