#!/usr/bin/env bash
set -euo pipefail
echo "--- install_qdrant.sh ---"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
QPORT=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['qdrant_http'])")
QGRPC=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['qdrant_grpc'])")
QIMG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['qdrant_image'])")
QNAME=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['qdrant_container'])")
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would docker run $QNAME"; exit 0; fi
docker rm -f "$QNAME" >/dev/null 2>&1 || true
docker run -d --name "$QNAME" --restart unless-stopped \
  -p "$QPORT:6333" -p "$QGRPC:6334" \
  -v ivcrag_qdrant:/qdrant/storage \
  "$QIMG"
echo "  [done] $QNAME started"
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$QPORT/" >/dev/null 2>&1; then echo "  [ok] qdrant up after ${i}s"; exit 0; fi
  sleep 1
done
echo "  [WARN] qdrant not healthy after 30s"
