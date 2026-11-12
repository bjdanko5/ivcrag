#!/usr/bin/env bash
set -euo pipefail
echo "--- check_ports.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
P_RAG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['rag_server'])" 2>/dev/null || echo 8091)
P_LLM=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['llama_server'])" 2>/dev/null || echo 8082)
P_QD=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['qdrant_http'])" 2>/dev/null || echo 6333)
for p in $P_RAG $P_LLM $P_QD; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$p$"; then
    echo "  [WARN] port $p busy"
  else
    echo "  [PASS] port $p free"
  fi
done
exit 0
