#!/usr/bin/env bash
set -euo pipefail
echo "--- install_docker.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
IMG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['llama_image'])")
QIMG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['qdrant_image'])")
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would pull $IMG and $QIMG"; exit 0; fi
docker pull "$IMG"
docker pull "$QIMG"
echo "  [done] images pulled"
