#!/bin/bash
# Server fix script — re-ingest papers after ChromaDB reset
set -e

API_KEY="944fa7cc56510c1a3860cdc9e220dd84f8ddfeea1cd0be25ceab9d63f3e42c21"
BASE="http://localhost:8000"

echo "=== Re-ingesting papers ==="
curl -s -X POST "${BASE}/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{}'

echo ""
echo "=== Checking vector store stats ==="
curl -s "${BASE}/store/stats" \
  -H "X-API-Key: ${API_KEY}"

echo ""
echo "=== Checking papers ==="
curl -s "${BASE}/store/papers" \
  -H "X-API-Key: ${API_KEY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Papers: {len(d)}')" 2>/dev/null || echo "(raw output above)"

echo ""
echo "=== Done ==="
