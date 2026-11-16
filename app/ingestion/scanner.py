"""Scanning lifecycle for the document index."""
import asyncio
import os
from pathlib import Path
from typing import Dict

from app.state import config, state
from app.ingestion.extractors import extract_text
from app.ingestion.indexing import _load_hashes, _save_hashes, delete_file_from_index, get_file_hash, index_file


def scan_docs_dir() -> dict:
    state.log.debug(
        f"[scan_docs_dir] Старт прохода. DOCS_DIR={config.DOCS_DIR}, exists={config.DOCS_DIR.exists()}, tracked={len(state.file_hashes)}"
    )

    if not config.DOCS_DIR.exists():
        state.log.warning(f"[scan_docs_dir] Папка {config.DOCS_DIR} не существует. Создаю...")
        config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        return {"indexed": 0, "deleted": 0, "skipped": 0, "note": "docs_dir_created"}

    current_files: Dict[Path, str] = {}
    for root, dirs, files in os.walk(config.DOCS_DIR):
        dirs[:] = [directory for directory in dirs if directory not in config.IGNORE_DIRS]
        for file_name in files:
            file_path = Path(root) / file_name
            if file_path.suffix.lower() in config.ALLOWED_EXTENSIONS:
                current_files[file_path] = get_file_hash(file_path)

    state.log.debug(
        f"[scan_docs_dir] Найдено файлов: {len(current_files)} (отслеживается: {len(state.file_hashes)})"
    )

    indexed, deleted, skipped = 0, 0, 0

    for old_path in list(state.file_hashes.keys()):
        if old_path not in current_files:
            state.log.info(f"[scan_docs_dir] ОБНАРУЖЕНО УДАЛЕНИЕ: {old_path.name}")
            delete_file_from_index(old_path.name)
            del state.file_hashes[old_path]
            deleted += 1

    for path, current_hash in current_files.items():
        is_new = path not in state.file_hashes
        is_changed = (not is_new) and state.file_hashes[path] != current_hash
        if is_new or is_changed:
            reason = "НОВЫЙ" if is_new else "ИЗМЕНЁН"
            state.log.info(f"[scan_docs_dir] ОБНАРУЖЕН {reason} файл: {path.name}")
            count = index_file(path)
            state.file_hashes[path] = current_hash
            if count > 0:
                indexed += 1
            else:
                skipped += 1
                state.log.warning(f"[scan_docs_dir] Файл пропущен (0 чанков): {path.name}")

    summary = {
        "indexed": indexed,
        "deleted": deleted,
        "skipped": skipped,
        "total_tracked": len(state.file_hashes),
    }
    state.log.debug(f"[scan_docs_dir] Итог прохода: {summary}")
    _save_hashes()
    return summary


async def periodic_scan():
    state.log.info(f"[periodic_scan] ЗАПУЩЕН. DOCS_DIR={config.DOCS_DIR}, интервал={config.SCAN_INTERVAL}с")
    cycle = 0
    while True:
        cycle += 1
        state.log.info(f"[periodic_scan] Цикл #{cycle}: старт скана")
        try:
            summary = await asyncio.to_thread(scan_docs_dir)
            state.log.info(f"[periodic_scan] Цикл #{cycle}: результат {summary}")
        except asyncio.CancelledError:
            state.log.info("[periodic_scan] Отменён")
            raise
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[periodic_scan] Цикл #{cycle}: ИСКЛЮЧЕНИЕ: {exc}")
            state.log.error("\n".join(__import__("traceback").format_exception(type(exc), exc, exc.__traceback__)))
        try:
            await asyncio.sleep(config.SCAN_INTERVAL)
        except asyncio.CancelledError:
            state.log.info("[periodic_scan] Отменён во время сна")
            raise


__all__ = ["scan_docs_dir", "periodic_scan"]
