#!/usr/bin/env bash
set -euo pipefail
echo "--- check_models.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
GGUF=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['models']['llm_gguf'])" 2>/dev/null || echo Qwen_Qwen3-0.6B-Q4_K_M.gguf)
MDIR=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['paths']['models_dir'])" 2>/dev/null || echo "$HOME/ivcrag/models")
if [[ -f "$MDIR/$GGUF" ]]; then echo "  [PASS] $MDIR/$GGUF"; else echo "  [FAIL] $MDIR/$GGUF missing"; exit 1; fi
