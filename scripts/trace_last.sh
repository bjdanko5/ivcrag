#!/usr/bin/env bash
# Показать последний трейс: тайминги, retrieval, контекст, промпт, ответ.
set -euo pipefail
F=$(find ~/ivcrag/logs/traces -type f -name "*.json" -print0 | xargs -0 ls -t | head -1 2>/dev/null)
[ -n "${F:-}" ] || { echo "нет трейсов"; exit 1; }
echo "== $F"
echo "--- query: $(jq -r '.request.query' "$F")"
echo "--- timings:"; jq '.timings_ms' "$F"
echo "--- categories:"; jq -r '.stages[] | "  \(.category) @\(.t_ms)ms"' "$F"
echo "--- llm_request:"; jq '.stages[] | select(.category=="llm_request") | .data | del(.prompt)' "$F"
echo "--- llm_response usage:"; jq '.stages[] | select(.category=="llm_response") | .data | {answer_chars, usage, finish_reason}' "$F"
echo "--- retrieval hits:"; jq '.stages[] | select(.category=="retrieval") | .data.hits[] | {rank, source, chunk_index, score, text80: (.text[0:80])}' "$F"
echo "--- context (первые 30 строк):"; jq -r '.stages[] | select(.category=="context") | .data.text' "$F" | head -30