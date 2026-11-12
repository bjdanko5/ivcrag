#!/usr/bin/env bash
set -euo pipefail
echo "--- install_python.sh ---"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/venv"
MIRROR="${IVCRAG_PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
MIRROR_HOST="${IVCRAG_PIP_MIRROR_HOST:-pypi.tuna.tsinghua.edu.cn}"

if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then
  echo "  [dry] would create venv $VENV and pip install from $MIRROR"
  exit 0
fi

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

cat > "$VENV/pip.conf" <<PIPEOF
[global]
index-url = $MIRROR
trusted-host = $MIRROR_HOST
timeout = 120
PIPEOF

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip wheel --index-url "$MIRROR" --trusted-host "$MIRROR_HOST"
pip install -r "$ROOT/app/requirements.txt" --index-url "$MIRROR" --trusted-host "$MIRROR_HOST"
echo "  [done] venv ready at $VENV (mirror: $MIRROR)"
