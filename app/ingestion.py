import hashlib
import json as _json
import os
import re
import traceback
from pathlib import Path
from typing import List, Dict

import state
from config import (
    ALLOWED_EXTENSIONS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DOCS_DIR,
    IGNORE_DIRS,
    SCAN_HASHES_FILE,
    SCAN_INTERVAL,
    SCAN_METHOD,
    SCAN_PERSIST,
    BATCH_SIZE,
)
from config import _normalize_text


def _extract_docx(path: Path) -> str:
    import docx
    doc = docx.Document(str(path))
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] DOCX {path.name}: {len(text)} символов")
    return text


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        if t.strip():
            parts.append(f"=== Page {i+1} ===\n{t}")
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] PDF {path.name}: {len(text)} символов, страниц: {len(reader.pages)}")
    return text


def _extract_xlsx(path: Path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"=== Лист: {sheet.title} ===")
        for row in sheet.iter_rows(values_only=True):
            vals = [str(v) if v is not None else "" for v in row]
            if any(vals):
                parts.append(" | ".join(vals))
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] XLSX {path.name}: {len(text)} символов")
    return text


def _extract_docx_table_rows(path: Path) -> List[str]:
    import docx
    doc = docx.Document(str(path))
    enriched_rows = []
    for table in doc.tables:
        if not table.rows:
            continue
        header_row = table.rows[0]
        headers = [c.text.strip().replace("\n", " ") for c in header_row.cells]
        for row in table.rows[1:]:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if not any(cells):
                continue
            if len(headers) == len(cells):
                parts = [f"{h}: {c}" for h, c in zip(headers, cells) if c]
                chunk = f"[{path.name}] " + " | ".join(parts)
            else:
                chunk = f"[{path.name}] " + " | ".join(cells)
            enriched_rows.append(chunk)
    return enriched_rows


def _extract_pdf_table_rows(path: Path) -> List[str]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    enriched_rows = []
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"
    full_text = re.sub(r'<[^>]+>', ' ', full_text)
    full_text = re.sub(r'\s+', ' ', full_text)
    pattern = re.compile(r'(\d{1,2})\s*([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*(\d{3})\s*100\s*(\d{3})\s*(8\(\d{3,4}\)[\d\-]+)')
    matches = pattern.findall(full_text)
    for match in matches:
        num, fio, vnut, obl, gorod = match
        chunk = f"[{path.name}] №: {num} | Ф.И.О.: {fio} | Внутренний: {vnut} | Городской: {gorod}"
        enriched_rows.append(chunk)
    return enriched_rows


def _extract_xlsx_table_rows(path: Path) -> List[str]:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    enriched_rows = []
    for sheet in wb.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        headers = None
        last_dept = ""
        last_dept_phone = ""
        for row in rows_iter:
            vals = [str(v).strip().replace("\n", " ") if v is not None else "" for v in row]
            if not any(vals):
                continue
            if headers is None:
                headers = vals
                continue
            for k, h in enumerate(headers):
                h_norm = _normalize_text(h)
                if h_norm in {'отдел', 'отдел в тел.'}:
                    if k < len(vals):
                        if vals[k]:
                            if h_norm == 'отдел':
                                last_dept = vals[k]
                            else:
                                last_dept_phone = vals[k]
                        else:
                            vals[k] = last_dept if h_norm == 'отдел' else last_dept_phone
            parts = []
            fio_multi = []
            for h, v in zip(headers, vals):
                if not v:
                    continue
                if _normalize_text(h) in {'ф.и.о.', 'фио', 'фамилия'}:
                    found = re.findall(r'[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}', v)
                    found = [x for x in found if len(x.split()) >= 2]
                    if len(found) > 1:
                        fio_multi = found
                        continue
                parts.append(f"{h}: {v}")
            if fio_multi:
                for one_fio in fio_multi:
                    person_parts = [f"Ф.И.О.: {one_fio}"] + parts
                    enriched_rows.append(f"[{path.name}] " + " | ".join(person_parts))
            elif parts:
                enriched_rows.append(f"[{path.name}] " + " | ".join(parts))
    state.log.debug(f"[_extract_xlsx_table_rows] {path.name}: {len(enriched_rows)} строк")
    return enriched_rows


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    state.log.debug(f"[extract_text] Файл: {path.name}, расширение: {ext}")

    if ext in {".txt", ".md", ".markdown", ".rst", ".py", ".sh", ".bash",
               ".php", ".js", ".ts", ".json", ".yaml", ".yml",
               ".html", ".css", ".sql"}:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            state.log.debug(f"[extract_text] Прочитано {len(text)} символов из {path.name}")
            return text
        except Exception as e:
            state.log.error(f"[extract_text] Ошибка чтения {path.name}: {e}")
            return ""

    if ext == ".docx":
        try:
            enriched = _extract_docx_table_rows(path)
            if enriched:
                return "\n---\n".join(enriched)
            return _extract_docx(path)
        except Exception as e:
            state.log.error(f"[extract_text] Ошибка DOCX {path.name}: {e}")
            return ""

    if ext == ".pdf":
        try:
            enriched = _extract_pdf_table_rows(path)
            if enriched:
                state.log.debug(f"[extract_text] PDF {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            return _extract_pdf(path)
        except Exception as e:
            state.log.error(f"[extract_text] Ошибка PDF {path.name}: {e}")
            return ""

    if ext in {".xlsx", ".xls"}:
        try:
            enriched = _extract_xlsx_table_rows(path)
            if enriched:
                state.log.debug(f"[extract_text] XLSX {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            return _extract_xlsx(path)
        except Exception as e:
            state.log.error(f"[extract_text] Ошибка XLSX {path.name}: {e}")
            return ""

    if ext == ".doc":
        state.log.warning(f"[extract_text] .doc не поддержан: {path.name}")
        return ""

    state.log.warning(f"[extract_text] Неизвестное расширение: {ext} ({path.name})")
    return ""


def chunk_text(text: str, max_chars: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    state.log.debug(f"[chunk_text] Получено {len(chunks)} чанков из {len(text)} символов")
    return chunks


def get_file_hash(path: Path) -> str:
    if state.SCAN_METHOD if hasattr(state, 'SCAN_METHOD') else False:
        pass
    if "mtime" == state.SCAN_METHOD if hasattr(state, 'SCAN_METHOD') else "mtime":
        pass
    import config
    if config.SCAN_METHOD == "mtime":
        try:
            st = path.stat()
            h = f"{st.st_mtime_ns}_{st.st_size}"
            state.log.debug(f"[get_file_hash] {path.name} (mtime) -> {h}")
            return h
        except Exception as e:
            state.log.error(f"[get_file_hash] stat {path.name}: {e}")
            return ""
    hasher = hashlib.md5()
    try:
        with open(path, "rb") as f:
            hasher.update(f.read())
        h = hasher.hexdigest()
        state.log.debug(f"[get_file_hash] {path.name} (md5) -> {h[:12]}…")
        return h
    except Exception as e:
        state.log.error(f"[get_file_hash] md5 {path.name}: {e}")
        return ""


def _load_hashes():
    if not SCAN_PERSIST:
        state.log.info("[hashes] persist=false — хеши не загружаются")
        return
    if not SCAN_HASHES_FILE.exists():
        state.log.info(f"[hashes] {SCAN_HASHES_FILE} не найден — будет первичная индексация")
        return
    try:
        raw = _json.loads(SCAN_HASHES_FILE.read_text(encoding="utf-8"))
        state.file_hashes = {Path(k): v for k, v in raw.items()}
        state.log.info(f"[hashes] Загружено {len(state.file_hashes)} хешей из {SCAN_HASHES_FILE}")
    except Exception as e:
        state.log.warning(f"[hashes] load failed: {e}")


def _save_hashes():
    if not SCAN_PERSIST:
        return
    try:
        SCAN_HASHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        raw = {str(k): v for k, v in state.file_hashes.items()}
        SCAN_HASHES_FILE.write_text(_json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        state.log.warning(f"[hashes] save failed: {e}")


def delete_file_from_index(source_name: str):
    state.log.info(f"[delete_file_from_index] Удаляю {source_name} из Qdrant...")
    try:
        state.qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=state.models.Filter(
                must=[state.models.FieldCondition(
                    key="source", match=state.models.MatchValue(value=source_name)
                )]
            ),
        )
        state.log.info(f"[delete_file_from_index] Успешно удалён {source_name}")
    except Exception as e:
        state.log.error(f"[delete_file_from_index] Ошибка удаления {source_name}: {e}")


def index_file(path: Path) -> int:
    source_name = path.name
    state.log.info(f"[index_file] НАЧАЛО индексации: {source_name}")
    text = extract_text(path)
    if not text.strip():
        state.log.warning(f"[index_file] ПУСТОЙ текст после extract_text: {source_name}")
        return 0

    state.log.debug(f"[index_file] Текст получен: {len(text)} символов")
    delete_file_from_index(source_name)

    if ("Таблица: " in text or "№: " in text) and "\n---\n" in text:
        raw_chunks = text.split("\n---\n")
        state.log.debug(f"[index_file] Таблица обнаружена, разбито на {len(raw_chunks)} строк-чанков")
    else:
        raw_chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)

    if not raw_chunks:
        state.log.warning(f"[index_file] chunk_text вернул 0 чанков: {source_name}")
        return 0

    prepared_texts = [f"search_document: {ch}" for ch in raw_chunks]
    points = []
    total_batches = (len(prepared_texts) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(prepared_texts), BATCH_SIZE):
        batch_num = i // BATCH_SIZE + 1
        batch_texts = prepared_texts[i:i + BATCH_SIZE]
        batch_raw = raw_chunks[i:i + BATCH_SIZE]
        state.log.debug(f"[index_file] Батч {batch_num}/{total_batches} ({len(batch_texts)} текстов) для {source_name}")

        try:
            dense_texts = [f"passage: {t}" for t in batch_raw]
            dense_vectors = [v.tolist() for v in state._dense_model.embed(dense_texts)]
            sparse_vectors = list(state._sparse_model.embed(batch_raw))
            state.log.debug(f"[index_file] Получено {len(dense_vectors)} dense и {len(sparse_vectors)} sparse векторов")
        except Exception as e:
            state.log.error(f"[index_file] Ошибка векторизации батча {batch_num} для {source_name}: {e}")
            state.log.debug(traceback.format_exc())
            continue

        for j, (dense_vec, sparse_emb) in enumerate(zip(dense_vectors, sparse_vectors)):
            chunk_idx = i + j
            chunk_id = hashlib.md5(f"{source_name}_{chunk_idx}".encode()).hexdigest()
            sparse_vec = state.models.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist(),
            )
            points.append(state.models.PointStruct(
                id=chunk_id,
                vector={"dense": dense_vec, "sparse": sparse_vec},
                payload={
                    "source": source_name,
                    "chunk_index": chunk_idx,
                    "text": batch_raw[j],
                },
            ))

    if points:
        state.log.debug(f"[index_file] Отправляю {len(points)} точек в Qdrant...")
        try:
            state.qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
            state.log.info(f"[index_file] УСПЕХ: {len(points)} чанков для {source_name}")
        except Exception as e:
            state.log.error(f"[index_file] Ошибка upsert в Qdrant для {source_name}: {e}")
            return 0
    else:
        state.log.warning(f"[index_file] Нет точек для загрузки: {source_name}")
        return 0

    return len(points)


def scan_docs_dir() -> dict:
    state.log.debug(f"[scan_docs_dir] Старт прохода. DOCS_DIR={DOCS_DIR}, exists={DOCS_DIR.exists()}, tracked={len(state.file_hashes)}")
    if not DOCS_DIR.exists():
        state.log.warning(f"[scan_docs_dir] Папка {DOCS_DIR} не существует. Создаю...")
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        return {"indexed": 0, "deleted": 0, "skipped": 0, "note": "docs_dir_created"}

    current_files: Dict[Path, str] = {}
    for root, dirs, files in os.walk(DOCS_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in ALLOWED_EXTENSIONS:
                current_files[file_path] = get_file_hash(file_path)

    state.log.debug(f"[scan_docs_dir] Найдено файлов: {len(current_files)} (отслеживается: {len(state.file_hashes)})")

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
            n = index_file(path)
            state.file_hashes[path] = current_hash
            if n > 0:
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
    import asyncio
    state.log.info(f"[periodic_scan] ЗАПУЩЕН. DOCS_DIR={DOCS_DIR}, интервал={SCAN_INTERVAL}с")
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
        except Exception as e:
            state.log.error(f"[periodic_scan] Цикл #{cycle}: ИСКЛЮЧЕНИЕ: {e}")
            state.log.error(traceback.format_exc())
        try:
            await asyncio.sleep(SCAN_INTERVAL)
        except asyncio.CancelledError:
            state.log.info("[periodic_scan] Отменён во время сна")
            raise


__all__ = [
    "_extract_docx",
    "_extract_pdf",
    "_extract_xlsx",
    "_extract_docx_table_rows",
    "_extract_pdf_table_rows",
    "_extract_xlsx_table_rows",
    "extract_text",
    "chunk_text",
    "get_file_hash",
    "_load_hashes",
    "_save_hashes",
    "delete_file_from_index",
    "index_file",
    "scan_docs_dir",
    "periodic_scan",
]
