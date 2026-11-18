#!/usr/bin/env python3
"""CLI для управления per-request трассировкой ivcrag.

  python3 scripts/trace.py status         # состояние
  python3 scripts/trace.py on             # включить
  python3 scripts/trace.py off            # выключить
  python3 scripts/trace.py toggle         # переключить
  python3 scripts/trace.py last           # последний трейс (кратко)
  python3 scripts/trace.py last-full      # последний трейс (полностью)
  python3 scripts/trace.py list [N]       # последние N трейсов за сегодня
  python3 scripts/trace.py query <текст>  # запрос к /v1/chat/completions + трейс
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://localhost:8091"
TRACES_DIR = Path.home() / "ivcrag/logs/traces"


def _http(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode(errors="replace")}
    except urllib.error.URLError as e:
        return {"_url_error": str(e)}


def _today_dir() -> Path:
    import datetime
    return TRACES_DIR / datetime.date.today().isoformat()


def _last_trace() -> Path | None:
    d = _today_dir()
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def cmd_status(_args):
    print(json.dumps(_http("GET", "/admin/trace"), ensure_ascii=False, indent=2))


def cmd_set(on: bool):
    r = _http("POST", f"/admin/trace?on={'1' if on else '0'}")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_toggle():
    print(json.dumps(_http("POST", "/admin/trace?toggle=1"), ensure_ascii=False, indent=2))


def cmd_last(_args):
    p = _last_trace()
    if not p:
        print(f"нет трейсов в {_today_dir()}")
        sys.exit(1)
    t = json.loads(p.read_text())
    print(f"== {p}")
    print(f"query:   {t['request']['query']}")
    print(f"status:  {t['status']}  client: {t.get('client_ip','')}")
    print(f"timings: {json.dumps(t['timings_ms'], ensure_ascii=False)}")
    print("stages:")
    for s in t["stages"]:
        print(f"  {s['t_ms']:>9.1f} ms  {s['category']}")
    for s in t["stages"]:
        if s["category"] == "llm_request":
            d = s["data"]
            print(f"llm_request: model={d.get('model')} endpoint={d.get('endpoint')} "
                  f"prompt_chars={d.get('prompt_chars')} max_tokens={d.get('max_tokens')}")
        if s["category"] == "llm_response":
            d = s["data"]
            print(f"llm_response: answer_chars={d.get('answer_chars')} "
                  f"finish={d.get('finish_reason')} usage={json.dumps(d.get('usage'), ensure_ascii=False)}")
        if s["category"] == "retrieval":
            hits = s["data"].get("hits") or []
            print(f"retrieval: {len(hits)} hits")
            for h in hits[:5]:
                print(f"  [{h.get('rank')}] {h.get('source')} chunk {h.get('chunk_index')} "
                      f"score={h.get('score')} {str(h.get('text'))[:70]!r}")
        if s["category"] == "context":
            d = s["data"]
            print(f"context: {d.get('chars')} chars, sources={d.get('sources')}")


def cmd_last_full(_args):
    p = _last_trace()
    if not p:
        print(f"нет трейсов в {_today_dir()}")
        sys.exit(1)
    print(p.read_text())


def cmd_list(args):
    d = _today_dir()
    if not d.exists():
        print(f"нет каталога {d}")
        return
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: args.n]
    for p in files:
        t = json.loads(p.read_text())
        print(f"{t['ts_start']}  total={t['timings_ms']['total']:>9.1f}ms  "
              f"status={t['status']:<6}  {t['request']['query'][:60]!r}")


def cmd_query(args):
    """Отправить запрос и показать трейс."""
    body = {"model": "rag", "messages": [{"role": "user", "content": args.text}]}
    print(f"POST /v1/chat/completions  query={args.text!r}")
    r = _http("POST", "/v1/chat/completions", body)
    if "_http_error" in r or "_url_error" in r:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(1)
    content = r["choices"][0]["message"]["content"]
    print(f"--- answer ({len(content)} chars) ---")
    print(content[:500] + ("..." if len(content) > 500 else ""))
    print(f"sources: {r.get('x_rag_sources')}  hits: {r.get('x_rag_hits')}")
    print("--- trace ---")
    cmd_last(None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("on").set_defaults(fn=lambda a: cmd_set(True))
    sub.add_parser("off").set_defaults(fn=lambda a: cmd_set(False))
    sub.add_parser("toggle").set_defaults(fn=lambda a: cmd_toggle())
    sub.add_parser("last").set_defaults(fn=cmd_last)
    sub.add_parser("last-full").set_defaults(fn=cmd_last_full)
    p_list = sub.add_parser("list"); p_list.add_argument("n", type=int, nargs="?", default=10); p_list.set_defaults(fn=cmd_list)
    p_q = sub.add_parser("query"); p_q.add_argument("text"); p_q.set_defaults(fn=cmd_query)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()