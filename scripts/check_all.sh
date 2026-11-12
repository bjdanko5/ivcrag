#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IVCRAG_ROOT="$ROOT"
export IVCRAG_CFG="$ROOT/config.yaml"
rc=0
for s in check_system check_python check_docker check_qdrant check_models check_ports; do
  echo
  bash "$ROOT/scripts/$s.sh" || rc=1
done
echo
echo "=== check_all result: $([[ $rc -eq 0 ]] && echo ALL-PASS || echo HAS-FAIL) ==="
exit $rc
