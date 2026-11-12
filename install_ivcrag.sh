#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="$ROOT/config.yaml"
DRY=0; YES=0; FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)  CFG="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    --yes)     YES=1; shift;;
    --force)   FORCE=1; shift;;
    -h|--help) echo "Usage: $0 [--config file] [--dry-run] [--yes] [--force]"; exit 0;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done
export IVCRAG_ROOT="$ROOT"
export IVCRAG_CFG="$CFG"
export IVCRAG_DRY="$DRY"
export IVCRAG_YES="$YES"
export IVCRAG_FORCE="$FORCE"

echo "=================================================="
echo " ivcrag installer"
echo " root=$ROOT  cfg=$CFG  dry-run=$DRY  yes=$YES"
echo "=================================================="

step() { echo; echo "=== $1 ==="; }
run_check() {
  local s="$1"
  if bash "$ROOT/scripts/$s"; then echo "  -> PASS ($s)"; return 0
  else echo "  -> FAIL ($s)"; return 1; fi
}

step "1. system checks"
run_check check_system.sh || { echo "Fix system first."; exit 1; }
run_check check_python.sh || true
run_check check_docker.sh || true

step "2. qdrant"
if ! bash "$ROOT/scripts/check_qdrant.sh"; then
  if [[ $DRY -eq 1 ]]; then echo "  [dry] would run install_qdrant.sh"
  else bash "$ROOT/scripts/install_qdrant.sh"; fi
fi

step "3. models"
if ! bash "$ROOT/scripts/check_models.sh"; then
  if [[ $DRY -eq 1 ]]; then echo "  [dry] would run download_models.sh"
  else bash "$ROOT/scripts/download_models.sh"; fi
fi

step "4. ports"
run_check check_ports.sh || { echo "Ports busy."; exit 1; }

step "5. python venv"
if [[ ! -d "$ROOT/venv" ]]; then
  if [[ $DRY -eq 1 ]]; then echo "  [dry] would run install_python.sh"
  else bash "$ROOT/scripts/install_python.sh"; fi
else echo "  venv exists: $ROOT/venv"; fi

step "6. .env"
if [[ ! -f "$ROOT/.env" ]]; then
  if [[ $DRY -eq 1 ]]; then echo "  [dry] would copy .env.example -> .env"
  else cp "$ROOT/.env.example" "$ROOT/.env"; echo "  created $ROOT/.env"; fi
else echo "  .env exists"; fi

step "7. systemd"
if [[ $YES -eq 1 ]]; then
  if [[ $DRY -eq 1 ]]; then echo "  [dry] would install systemd units"
  else
    sudo cp "$ROOT"/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now ivcrag-qdrant.service ivcrag-llama.service ivcrag-server.service
  fi
else echo "  skipped (use --yes)"; fi

step "8. smoke test"
if [[ $DRY -eq 1 ]]; then echo "  [dry] would run smoke_test.sh"
else sleep 5; bash "$ROOT/scripts/smoke_test.sh" || echo "  smoke FAILED"; fi

echo
echo "=== DONE ==="
