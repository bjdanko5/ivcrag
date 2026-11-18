#!/usr/bin/env python3
"""Создаёт пустые файлы-заготовки для ручного заполнения.

  python3 scripts/scaffold.py --check
  python3 scripts/scaffold.py
  python3 scripts/scaffold.py --revert

Существующие файлы НЕ перезаписываются (только создаются отсутствующие).
"""
import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path.home() / "ivcrag"

FILES = [
    "app/api/admin.py",
    "scripts/trace.py",
    "scripts/logs.py",
    "docs/DEBUGGING.md",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    if args.revert:
        n = 0
        for rel in FILES:
            p = ROOT / rel
            b = p.with_suffix(p.suffix + ".bak.scaffold")
            if b.exists():
                shutil.move(str(b), str(p))
                print(f"✓ восстановлен {p}")
                n += 1
            elif p.exists():
                p.unlink()
                print(f"✓ удалён {p}")
                n += 1
        if not n:
            print("✗ нечего откатывать")
            return 1
        return 0

    for rel in FILES:
        p = ROOT / rel
        if p.exists():
            print(f"= {p}: уже существует, не трогаю")
            continue
        if args.check:
            print(f"~ {p}: будет создан")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        print(f"✓ создан {p}")

    if not args.check:
        # пометим scripts/* как исполняемые — пригодится, когда заполните
        for rel in ("scripts/trace.py", "scripts/logs.py"):
            p = ROOT / rel
            if p.exists():
                p.chmod(0o755)
                print(f"✓ chmod +x {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())