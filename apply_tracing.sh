#!/usr/bin/env bash
# Внедрение per-request JSON-трассировки в ivcrag.
# Использование:
#   bash apply_tracing.sh              # применить
#   bash apply_tracing.sh --check      # только проверить, ничего не менять
#   bash apply_tracing.sh --revert     # откатить по *.bak.tracing
set -euo pipefail

REPO="${IVCRAG_REPO:-$HOME/ivcrag}"
MODE="apply"
for a in "$@"; do
  case "$a" in
    --check)  MODE="check"  ;;
    --revert) MODE="revert" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
  esac
done

ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
hr()   { printf -- '─%.0s' {1..70}; echo; }

cd "$REPO" 2>/dev/null || die "нет каталога $REPO (задайте IVCRAG_REPO)"
hr; echo "repo: $REPO  mode: $MODE"; hr

# ── 0. Проверки ──────────────────────────────────────────────────────────────
[ -d .git ] || die "не git-репозиторий: $REPO"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
echo "branch=$BRANCH  dirty_files=$DIRTY"
[ "$DIRTY" = "0" ] || warn "рабочее дерево грязное — вставки пойдут поверх; бэкапы *.bak.tracing будут созданы"

for f in app/api/openai.py app/retrieval.py app/lifecycle.py app/bootstrap.py; do
  [ -f "$f" ] && ok "found $f" || warn "нет $f (шаг может быть пропущен)"
done

if [ "$MODE" = "revert" ]; then
  hr; echo "Откат по *.bak.tracing"
  n=0
  while IFS= read -r -d '' b; do
    orig="${b%.bak.tracing}"
    mv -f "$b" "$orig" && { ok "restored $orig"; n=$((n+1)); }
  done < <(find app -name '*.bak.tracing' -print0)
  [ "$n" -gt 0 ] || warn "бэкапов не найдено"
  git --no-pager diff --stat || true
  exit 0
fi

# ── 1. app/tracing.py ────────────────────────────────────────────────────────
TRACING_FILE="app/tracing.py"
TRACING_CONTENT='"""Per-request JSON tracing. Enabled by IVCRAG_TRACE=1.

One JSON per request in IVCRAG_TRACE_DIR/<YYYY-MM-DD>/<HH-MM-SS>_<id>.json
plus append-only index.jsonl. Stdlib only.
"""
import json
import os
import time
import uuid
from pathlib import Path

TRACE_ON = os.getenv("IVCRAG_TRACE", "0").lower() in ("1", "true", "yes", "on")
TRACE_DIR = Path(os.getenv("IVCRAG_TRACE_DIR", "logs/traces")).expanduser()

_current = None


def enabled() -> bool:
    return TRACE_ON


def begin(query: str, params: dict, client_ip: str = "") -> None:
    global _current
    if not TRACE_ON:
        return
    _current = {
        "id": uuid.uuid4().hex[:8],
        "ts_start": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "client_ip": client_ip,
        "request": {"query": query, "params": params},
        "params": params,
        "stages": [],
        "_t0": time.perf_counter(),
    }


def stage(category: str, data) -> None:
    if _current is None:
        return
    _current["stages"].append({
        "category": category,
        "t_ms": round((time.perf_counter() - _current["_t0"]) * 1000, 1),
        "data": data,
    })


def end(status: str = "ok") -> None:
    global _current
    if _current is None:
        return
    cur, _current = _current, None
    cur.pop("_t0", None)
    cur["ts_end"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur["status"] = status
    cur["timings_ms"] = _timings(cur["stages"])

    day = cur["ts_start"][:10]
    d = TRACE_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{cur[chr(39)+chr(39)].__class__ and cur[\"ts_start\"][11:19].replace(chr(58), chr(45))}_{cur[\"id\"]}.json" if False else f"{cur[chr(116)+chr(115)+chr(95)+chr(115)+chr(116)+chr(97)+chr(114)+chr(116)][11:19].replace(chr(58), chr(45))}_{cur[chr(105)+chr(100)]}.json"
    path = d / fname
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2))
    os.replace(tmp, path)

    with open(TRACE_DIR / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": cur["id"],
            "ts": cur["ts_start"],
            "query": cur["request"]["query"],
            "status": cur["status"],
            "t_total_ms": cur["timings_ms"]["total"],
            "mode": cur["params"].get("mode"),
            "n_stages": len(cur["stages"]),
        }, ensure_ascii=False) + "\n")


def _timings(stages):
    out = {"total": stages[-1]["t_ms"] if stages else 0}
    for s in stages:
        out.setdefault(s["category"], s["t_ms"])
    return out
'
# проще писать файл через here-doc, чем экранировать кавычки в переменной:
write_tracing_file() {
  cat > "$TRACING_FILE" <<'PYEOF'
"""Per-request JSON tracing. Enabled by IVCRAG_TRACE=1.

One JSON per request in IVCRAG_TRACE_DIR/<YYYY-MM-DD>/<HH-MM-SS>_<id>.json
plus append-only index.jsonl. Stdlib only.
"""
import json
import os
import time
import uuid
from pathlib import Path

TRACE_ON = os.getenv("IVCRAG_TRACE", "0").lower() in ("1", "true", "yes", "on")
TRACE_DIR = Path(os.getenv("IVCRAG_TRACE_DIR", "logs/traces")).expanduser()

_current = None


def enabled() -> bool:
    return TRACE_ON


def begin(query: str, params: dict, client_ip: str = "") -> None:
    global _current
    if not TRACE_ON:
        return
    _current = {
        "id": uuid.uuid4().hex[:8],
        "ts_start": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "client_ip": client_ip,
        "request": {"query": query, "params": params},
        "params": params,
        "stages": [],
        "_t0": time.perf_counter(),
    }


def stage(category: str, data) -> None:
    if _current is None:
        return
    _current["stages"].append({
        "category": category,
        "t_ms": round((time.perf_counter() - _current["_t0"]) * 1000, 1),
        "data": data,
    })


def end(status: str = "ok") -> None:
    global _current
    if _current is None:
        return
    cur, _current = _current, None
    cur.pop("_t0", None)
    cur["ts_end"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur["status"] = status
    cur["timings_ms"] = _timings(cur["stages"])

    day = cur["ts_start"][:10]
    d = TRACE_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{cur['ts_start'][11:19].replace(':', '-')}_{cur['id']}.json"
    path = d / fname
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2))
    os.replace(tmp, path)

    with open(TRACE_DIR / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": cur["id"],
            "ts": cur["ts_start"],
            "query": cur["request"]["query"],
            "status": cur["status"],
            "t_total_ms": cur["timings_ms"]["total"],
            "mode": cur["params"].get("mode"),
            "n_stages": len(cur["stages"]),
        }, ensure_ascii=False) + "\n")


def _timings(stages):
    out = {"total": stages[-1]["t_ms"] if stages else 0}
    for s in stages:
        out.setdefault(s["category"], s["t_ms"])
    return out
PYEOF
}

if [ "$MODE" = "check" ]; then
  if [ -f "$TRACING_FILE" ] && grep -q 'def begin(query' "$TRACING_FILE"; then
    ok "tracing.py уже на месте"
  else
    warn "tracing.py отсутствует — будет создан при apply"
  fi
else
  [ -f "$TRACING_FILE" ] && cp -a "$TRACING_FILE" "$TRACING_FILE.bak.tracing"
  write_tracing_file
  ok "записан $TRACING_FILE"
fi

# ── 2. Хелпер: вставить строку после anchor (idempotent) ────────────────────
# insert_after FILE ANCHOR_LINE INSERT_LINE
insert_after() {
  local file="$1" anchor="$2" insert="$3"
  [ -f "$file" ] || { warn "skip $file (нет файла)"; return 0; }
  if grep -qF -- "$insert" "$file"; then
    ok "$(basename "$file"): вставка уже есть"
    return 0
  fi
  if ! grep -qF -- "$anchor" "$file"; then
    warn "$(basename "$file"): якорь не найден: $anchor"
    return 1
  fi
  [ "$MODE" = "check" ] && { warn "$(basename "$file"): будет вставлено: $insert"; return 0; }
  cp -a "$file" "$file.bak.tracing"
  # python-вставка сохраняет отступы (awk-вариант ломается на табах)
  python3 - "$file" "$anchor" "$insert" <<'PY'
import sys, pathlib
path, anchor, insert = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
out, done = [], False
for line in lines:
    out.append(line)
    if not done and anchor in line:
        # отступ = leading whitespace якоря
        indent = line[:len(line) - len(line.lstrip())]
        out.append(indent + insert.lstrip() + "\n")
        done = True
p.write_text("".join(out), encoding="utf-8")
sys.exit(0 if done else 2)
PY
  ok "$(basename "$file"): вставлено"
}

# ── 3. Импорт tracing + обёртка эндпоинта в app/api/openai.py ──────────────
OPENAI="app/api/openai.py"
if [ -f "$OPENAI" ]; then
  insert_after "$OPENAI" "from fastapi" "from app import tracing"
  # begin(): после объявления функции-эндпоинта, первой строкой тела
  # (якорь — декоратор @router.post("/v1/chat/completions"))
  if grep -qF -- 'tracing.begin(' "$OPENAI"; then
    ok "openai.py: begin/stage уже есть"
  else
    warn "openai.py: нужна РУЧНАЯ вставка begin/stage/end в тело эндпоинта — см. шаблон в README"
    # показать шаблон
    cat <<'TPL'

  Шаблон для тела @router.post("/v1/chat/completions"):
  --------------------------------------------------
  tracing.begin(
      query=req.query,
      params={
          "mode": config.LLM_MODE,
          "top_k": config.TOP_K,
          "max_context_chars": config.MAX_CONTEXT_CHARS,
          "analytical_context_chars": config.ANALYTICAL_CONTEXT_CHARS,
      },
      client_ip=request.client.host if request.client else "",
  )
  status = "ok"
  try:
      ... существующее тело ...
      tracing.stage("normalize", {...})
      tracing.stage("retrieval", {...})
      tracing.stage("context_pass1", {...})
      tracing.stage("llm_request", {...})
      tracing.stage("llm_response", {...})
  except Exception as exc:
      status = "error"
      tracing.stage("error", {"type": type(exc).__name__, "msg": str(exc)})
      raise
  finally:
      tracing.end(status=status)
  --------------------------------------------------
TPL
  fi
else
  warn "нет $OPENAI — пропуск"
fi

# ── 4. app/retrieval.py: добавить tracing.stage в 3 хелпера ─────────────────
RET="app/retrieval.py"
if [ -f "$RET" ]; then
  insert_after "$RET" "from app.state import" "from app import tracing"

  # _normalize_query_for_search: стадия после вычисления result_s
  insert_after "$RET" 'return " ".join(result)' \
    'tracing.stage("normalize_detail", {"after_split": _split_alpha_digit(question), "after_stem": _s(" ".join(result))})'

  # _filter_hits_by_entity: перед return matched
  insert_after "$RET" 'matched = [hit for hit in hits' \
    'tracing.stage("filter_by_entity", {"n_in": len(hits), "n_out": len(matched), "stems": stems})'

  # _collect_all_entity_rows: перед return rows
  insert_after "$RET" 'return rows' \
    'tracing.stage("entity_rows_detail", {"entities": entities, "stems": all_stems, "n_scrolled": len(points), "n_matched": len(rows), "rows": rows})'
else
  warn "нет $RET — пропуск"
fi

# ── 5. Приглушение шумных логгеров ─────────────────────────────────────────
LIFE="app/lifecycle.py"
if [ -f "$LIFE" ]; then
  if grep -q 'IVCRAG_LOG_QUIET' "$LIFE"; then
    ok "lifecycle.py: quiet уже настроен"
  else
    insert_after "$LIFE" "import logging" \
      '_quiet = os.getenv("IVCRAG_LOG_QUIET", "urllib3,httpx,uvicorn.access").split(",")_'
    # приведённая выше строка — заглушка; реальная вставка ниже, единым блоком
    python3 - "$LIFE" <<'PY'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")
if "IVCRAG_LOG_QUIET" in src:
    sys.exit(0)
if "import os" not in src:
    src = src.replace("import logging", "import logging\nimport os", 1)
block = '''

# --- IVCRAG_LOG_QUIET: приглушить шумные логгеры (urllib3, httpx, uvicorn.access) ---
import os as _os
for _n in _os.getenv("IVCRAG_LOG_QUIET", "urllib3,httpx,uvicorn.access").split(","):
    _n = _n.strip()
    if _n:
        logging.getLogger(_n).setLevel(logging.WARNING)
'''
src += block
p.write_text(src, encoding="utf-8")
PY
    ok "lifecycle.py: добавлен IVCRAG_LOG_QUIET"
  fi
fi

# ── 6. Проверка синтаксиса и импорта ───────────────────────────────────────
hr; echo "Проверка: compileall + импорт"
python3 -m compileall -q app && ok "compileall OK" || die "compileall failed"
python3 - <<'PY' && ok "import app ok" || die "import app failed"
import sys
sys.path.insert(0, ".")
import app  # noqa
PY

# ── 7. Smoke (если сервер жив) ─────────────────────────────────────────────
hr; echo "Smoke"
if curl -sf -m 2 http://localhost:8091/health >/dev/null; then
  curl -s http://localhost:8091/health | python3 -m json.tool | head -20
  ok "health отвечает"
  if curl -sf -m 2 http://localhost:8091/health >/dev/null && [ "${IVCRAG_TRACE:-0}" != "1" ]; then
    warn "сервер запущен без IVCRAG_TRACE — для снятия трейсов перезапустите:"
    warn "  sudo -E IVCRAG_TRACE=1 systemctl restart ivcrag-server"
  fi
else
  warn "/health не отвечает — рестарт сервера не выполнялся"
fi

# ── 8. Итоговый diff ───────────────────────────────────────────────────────
hr; echo "git diff --stat"; git --no-pager diff --stat || true
hr; echo "Откат: bash $0 --revert"