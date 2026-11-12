#!/usr/bin/env bash
set -euo pipefail
echo "--- check_qdrant.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
PORT=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['qdrant_http'])" 2>/dev/null || echo 6333)
if curl -sf "http://localhost:$PORT/healthz" >/dev/null 2>&1 || curl -sf "http://localhost:$PORT/" >/dev/null 2>&1; then
  echo "  [PASS] qdrant http on :$PORT"
  COLL=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['qdrant']['collection'])" 2>/dev/null || echo allm_docs)
  if curl -sf "http://localhost:$PORT/collections/$COLL" >/dev/null 2>&1; then
    echo "  [PASS] collection $COLL exists"
  else
    echo "  [WARN] collection $COLL not found"
  fi
  exit 0
fi
echo "  [FAIL] qdrant not reachable on :$PORT"
exit 1
