#!/usr/bin/env bash
set -euo pipefail
echo "--- install_system.sh ---"
if [[ "${IVCRAG_DRY:-0}" -eq 1 ]]; then echo "  [dry] would apt install"; exit 0; fi
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
$SUDO apt-get update
$SUDO apt-get install -y curl wget ca-certificates gnupg lsb-release python3 python3-venv python3-pip docker.io cifs-utils iproute2 lsof jq
echo "  [done] system packages installed"
if ! groups "$USER" | grep -qw docker; then
  echo "  [info] adding $USER to docker group (re-login needed)"
  $SUDO usermod -aG docker "$USER" || true
fi
