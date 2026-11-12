#!/usr/bin/env bash
set -euo pipefail
echo "--- check_python.sh ---"
command -v python3 >/dev/null || { echo "  [FAIL] python3 missing"; exit 1; }
pyv=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo "  python3 version: $pyv"
python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  && echo "  [PASS] python >= 3.10" \
  || { echo "  [FAIL] need python >= 3.10"; exit 1; }
python3 -c "import venv" 2>/dev/null \
  && echo "  [PASS] venv module" \
  || { echo "  [FAIL] python3-venv missing"; exit 1; }
echo "  [OK]"
