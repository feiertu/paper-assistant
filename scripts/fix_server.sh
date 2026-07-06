#!/bin/bash
# Paper Assistant — emergency fix script
# Run as: ssh root@47.86.236.212 "bash /opt/paper-assistant/fix.sh"
set -e
cd /opt/paper-assistant
echo "=== Removing broken container ==="
docker rm -f paper-assistant 2>/dev/null || true
echo "=== Starting fresh container ==="
docker compose up -d
echo "=== Waiting for healthy ==="
sleep 15
docker exec paper-assistant curl -s http://localhost:8000/health
echo ""
echo "=== Fix applied ==="
