#!/usr/bin/env bash
set -uo pipefail
ok=0; fail=0
chk() { if eval "$2" >/dev/null 2>&1; then echo "  [PASS] $1"; ok=$((ok+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }
echo "--- check_system.sh ---"
. /etc/os-release 2>/dev/null || true
chk "Ubuntu/Debian OS (${ID:-?} ${VERSION_ID:-?})" '[[ "${ID:-}" =~ ^(ubuntu|debian)$ ]]'
if lscpu 2>/dev/null | grep -qi avx; then echo "  [INFO] CPU has AVX"; else echo "  [WARN] CPU without AVX - do NOT install PyTorch"; fi
chk "RAM >= 4GB" '[[ $(awk "/MemTotal/{print int(\$2/1024/1024)}" /proc/meminfo) -ge 4 ]]'
chk "Disk HOME >= 10GB free" '[[ $(df -BG --output=avail "$HOME" | tail -1 | tr -dc 0-9) -ge 10 ]]'
chk "python3 present" 'command -v python3'
chk "docker present" 'command -v docker'
chk "sudo present" 'command -v sudo'
echo "--- summary: ok=$ok fail=$fail ---"
[[ $fail -eq 0 ]]
