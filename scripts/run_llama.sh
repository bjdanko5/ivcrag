#!/usr/bin/env bash
set -euo pipefail
echo "--- run_llama.sh ---"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${IVCRAG_CFG:-$ROOT/config.yaml}"
GGUF=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['models']['llm_gguf'])")
MDIR=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['paths']['models_dir'])")
LLMP=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['llama_server'])")
IMG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['llama_image'])")
NAME=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['llama_container'])")
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would start $NAME"; exit 0; fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  -p "$LLMP:8080" \
  -v "$MDIR:/models:ro" \
  "$IMG" -m "/models/$GGUF" --host 0.0.0.0 --port 8080 -c 4096 --jinja
echo "  [done] $NAME started"
