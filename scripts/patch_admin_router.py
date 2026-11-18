#!/usr/bin/env python3
"""Подключает admin_router в app/bootstrap.py.

  python3 scripts/patch_admin_router.py --check
  python3 scripts/patch_admin_router.py
  python3 scripts/patch_admin_router.py --revert
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path.home() / "ivcrag"
TARGET = ROOT / "app/bootstrap.py"
BAK = TARGET.with_suffix(TARGET.suffix + ".bak.admin_router")

IMPORT_ANCHOR = "from app.api.native import router as native_router"
IMPORT_INSERT = "from app.api.admin import router as admin_router\n"
INCLUDE_ANCHOR = "    application.include_router(native_router)"
INCLUDE_INSERT = "    application.include_router(admin_router)\n"


def patch(check: bool) -> int:
    if not TARGET.exists():
        print(f"✗ нет {TARGET}")
        return 1
    src = TARGET.read_text(encoding="utf-8")

    if "admin_router" in src:
        print(f"= {TARGET}: admin_router уже подключён")
        return 0

    if IMPORT_ANCHOR not in src:
        print(f"✗ {TARGET}: не найден якорь '{IMPORT_ANCHOR}'")
        print("  вставьте вручную: " + IMPORT_INSERT.strip())
        return 2
    if INCLUDE_ANCHOR not in src:
        print(f"✗ {TARGET}: не найден якорь '{INCLUDE_ANCHOR.strip()}'")
        print("  вставьте вручную: " + INCLUDE_INSERT.strip())
        return 2

    new = src.replace(IMPORT_ANCHOR, IMPORT_INSERT + IMPORT_ANCHOR, 1)
    new = new.replace(INCLUDE_ANCHOR, INCLUDE_INSERT + INCLUDE_ANCHOR, 1)

    if check:
        print(f"~ {TARGET}: будет добавлен admin_router (import + include)")
        return 0

    shutil.copy2(TARGET, BAK)
    TARGET.write_text(new, encoding="utf-8")
    print(f"✓ {TARGET}: admin_router подключён (бэкап {BAK.name})")

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