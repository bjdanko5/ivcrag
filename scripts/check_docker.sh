#!/usr/bin/env bash
set -euo pipefail
echo "--- check_docker.sh ---"
command -v docker >/dev/null || { echo "  [FAIL] docker missing"; exit 1; }
echo "  [PASS] docker binary"
docker info >/dev/null 2>&1 || { echo "  [FAIL] docker daemon not running or no perms"; exit 1; }
echo "  [PASS] docker daemon"
CFG="${IVCRAG_CFG:-$HOME/ivcrag/config.yaml}"
IMG=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['docker']['llama_image'])" 2>/dev/null || echo ghcr.io/ggml-org/llama.cpp:server)
if docker image inspect "$IMG" >/dev/null 2>&1; then echo "  [PASS] image $IMG"; else echo "  [FAIL] image $IMG not pulled"; exit 1; fi
