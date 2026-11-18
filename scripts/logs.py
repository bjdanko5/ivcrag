#!/usr/bin/env python3
"""Просмотр логов ivcrag.

  python3 scripts/logs.py errors [N]     # errors.log, последние N (default 50)
  python3 scripts/logs.py access [N]     # server.log (access-логи)
  python3 scripts/logs.py server [N]     # server.err.log
  python3 scripts/logs.py tracebacks [N] # только Traceback из server.err.log
  python3 scripts/logs.py all
"""
import argparse
import re
from pathlib import Path

LOGS = Path.home() / "ivcrag/logs"


def _tail(path: Path, n: int) -> None:
    if not path.exists():
        print(f"(нет файла {path})")
        return
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 200_000))
        lines = f.read().decode(errors="replace").splitlines()
    for line in lines[-n:]:
        print(line)


def _tracebacks(path: Path, n: int) -> None:
    if not path.exists():
        print(f"(нет файла {path})")
        return
    text = path.read_text(errors="replace")
    blocks = re.split(r"(?=^Traceback \(most recent call last\):)", text, flags=re.MULTILINE)
    blocks = [b for b in blocks if b.startswith("Traceback")]
    for b in blocks[-n:]:
        print(b.rstrip())
        print("-" * 60)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("errors", "access", "server"):
        p = sub.add_parser(name); p.add_argument("n", type=int, nargs="?", default=50); p.set_defaults(fn=name)
    p = sub.add_parser("tracebacks"); p.add_argument("n", type=int, nargs="?", default=3); p.set_defaults(fn="tracebacks")
    sub.add_parser("all").set_defaults(fn="all")
    args = ap.parse_args()

    if args.fn == "errors":
        _tail(LOGS / "errors.log", args.n)
    elif args.fn == "access":
        _tail(LOGS / "server.log", args.n)
    elif args.fn == "server":
        _tail(LOGS / "server.err.log", args.n)
    elif args.fn == "tracebacks":
        _tracebacks(LOGS / "server.err.log", args.n)
    elif args.fn == "all":
        print("=== errors.log ==="); _tail(LOGS / "errors.log", 30)
        print("\n=== access (server.log) ==="); _tail(LOGS / "server.log", 20)
        print("\n=== tracebacks (server.err.log) ==="); _tracebacks(LOGS / "server.err.log", 2)


if __name__ == "__main__":
    main()