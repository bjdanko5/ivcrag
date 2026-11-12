#!/usr/bin/env bash
set -uo pipefail
echo "--- smoke_test.sh ---"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${IVCRAG_CFG:-$ROOT/config.yaml}"
PORT=$(python3 -c "import yaml;d=yaml.safe_load(open('$CFG'));print(d['ports']['rag_server'])" 2>/dev/null || echo 8091)
BASE="http://localhost:$PORT"
PASS=0; FAIL=0

ask() {
  local q="$1"
  local payload
  payload=$(python3 -c "import json,sys;print(json.dumps({'model':'rag','messages':[{'role':'user','content':sys.argv[1]}]}))" "$q")
  curl -s "$BASE/v1/chat/completions" -H "Content-Type: application/json" -d "$payload" \
    | python3 -c "import sys,json
try:
    d=json.load(sys.stdin); c=d['choices'][0]['message']['content']; print(c[:300] if c else '<empty>')
except Exception as e: print('ERR:',e)"
}

check() {
  local q="$1"; local must="$2"
  echo "=== $q ==="
  local out; out=$(ask "$q")
  echo "$out"
  if echo "$out" | grep -qiE "$must"; then echo "  [PASS]"; PASS=$((PASS+1))
  else echo "  [FAIL] expected: $must"; FAIL=$((FAIL+1)); fi
}

check "Какие отделы есть?"          "отдел"
check "тел Жданко"                  "Жданк"
check "тел АУО"                     "АУО|АДМИНИСТРАТИВНО"
check "Сколько людей в ИТ отделе"   "ИТ|сотрудник"
check "Какой токен HF?"             "hf_"
check "Кто работает в ИТ отделе"    "ИТ"
check "отдел Дуванский"             "ОТДЕЛ"
echo "=== smoke: PASS=$PASS FAIL=$FAIL ==="
[[ $FAIL -eq 0 ]]
