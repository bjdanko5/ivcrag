#!/usr/bin/env python3
"""Добавляет errors.log (WARNING+) и приглушает шумные логгеры в app/lifecycle.py.

  python3 scripts/patch_errors_log.py --check
  python3 scripts/patch_errors_log.py
  python3 scripts/patch_errors_log.py --revert
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path.home() / "ivcrag"
TARGET = ROOT / "app/lifecycle.py"
BAK = TARGET.with_suffix(TARGET.suffix + ".bak.errors_log")

BLOCK = '''

# --- errors.log: только WARNING+ от app.* и ivcrag. Ротация 5 МБ x 3. ---
def _setup_errors_log() -> None:
    import logging as _logging
    import os as _os
    from logging.handlers import RotatingFileHandler as _RFH

    path = _os.getenv("IVCRAG_ERRORS_LOG", "logs/errors.log")
    _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
    h = _RFH(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    h.setLevel(_logging.WARNING)
    h.setFormatter(_logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    for name in ("ivcrag", "app"):
        _logging.getLogger(name).addHandler(h)

    # приглушить шумных
    for name in ("urllib3", "httpcore", "httpx", "uvicorn.access",
                 "embedding_server.periodic_scan"):
        _logging.getLogger(name).setLevel(_logging.WARNING)


_setup_errors_log()
'''


def patch(check: bool) -> int:
    if not TARGET.exists():
        print(f"✗ нет {TARGET}")
        return 1
    src = TARGET.read_text(encoding="utf-8")
    if "_setup_errors_log" in src:
        print(f"= {TARGET}: errors.log уже настроен")
        return 0

    if check:
        print(f"~ {TARGET}: будет добавлен _setup_errors_log()")
        return 0

    shutil.copy2(TARGET, BAK)
    TARGET.write_text(src.rstrip() + "\n" + BLOCK, encoding="utf-8")
    print(f"✓ {TARGET}: добавлен errors.log (бэкап {BAK.name})")

    rc = subprocess.run([sys.executable, "-m", "compileall", "-q", "app"],
                        cwd=ROOT).returncode
    if rc != 0:
        print("✗ compileall app — FAILED (откатите: --revert)")
        return 1
    print("✓ compileall app OK")
    return 0


def revert() -> int:
    if not BAK.exists():
        print(f"✗ нет бэкапа {BAK}")
        return 1
    shutil.move(str(BAK), str(TARGET))
    print(f"✓ восстановлен {TARGET}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    return revert() if args.revert else patch(args.check)


if __name__ == "__main__":
    sys.exit(main())