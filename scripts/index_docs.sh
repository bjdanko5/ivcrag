#!/usr/bin/env bash
set -euo pipefail
echo "--- index_docs.sh ---"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${IVCRAG_CFG:-$ROOT/config.yaml}"
DOCS=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['paths']['docs_source'])")
if [[ ! -d "$DOCS" ]]; then echo "  [FAIL] docs_source not mounted: $DOCS"; exit 1; fi
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would reindex $DOCS"; exit 0; fi
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
export IVCRAG_ROOT="$ROOT"
export IVCRAG_CFG="$CFG"
export IVCRAG_DOCS="$DOCS"
python3 "$ROOT/scripts/_index_helper.py"
