#!/usr/bin/env bash
set -euo pipefail
echo "--- download_models.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
GGUF=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['models']['llm_gguf'])")
URL=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['models']['llm_url'])")
MODELEMB=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['models']['embedding'])")
MDIR=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['paths']['models_dir'])")
VENV=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['paths']['venv'])")
mkdir -p "$MDIR"
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would download $URL"; exit 0; fi
if [[ ! -f "$MDIR/$GGUF" ]]; then
  echo "  downloading $GGUF ..."
  wget -O "$MDIR/$GGUF" "$URL"
else
  echo "  [skip] $GGUF exists"
fi
if [[ -d "$VENV" ]]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python3 -c "from fastembed import TextEmbedding; TextEmbedding(model_name='$MODELEMB'); print('  [ok] fastembed warmed')" || echo "  [WARN] fastembed warmup failed"
fi
