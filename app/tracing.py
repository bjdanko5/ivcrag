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
