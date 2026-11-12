#!/usr/bin/env bash
set -euo pipefail
echo "--- run_server.sh ---"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${IVCRAG_CFG:-$ROOT/config.yaml}"
LOG="$ROOT/logs/server_$(date +%Y%m%d_%H%M%S).log"
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
export IVCRAG_CFG="$CFG"
nohup python3 "$ROOT/app/embedding_server.py" >>"$LOG" 2>&1 &
PID=$!
echo "$PID" > "$ROOT/logs/server.pid"
echo "  [done] server PID=$PID log=$LOG"
