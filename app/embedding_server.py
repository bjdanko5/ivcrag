
# ===== ivcrag: load config from YAML =====
import os as _os
try:
    import yaml as _yaml
    _CFG_PATH = _os.environ.get("IVCRAG_CFG", "/home/user/ivcrag/config.yaml")
    _CFG = _yaml.safe_load(open(_CFG_PATH, encoding="utf-8"))
    def _c(*keys, default=None):
        cur = _CFG
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur
except Exception as _e:
    print(f"[ivcrag] WARN: config not loaded: {_e}")
    def _c(*keys, default=None):
        return default
# ===== /ivcrag =====

import os
import re
import uuid
import hashlib
import logging
import traceback
import requests
from pathlib import Path
from typing import List, Optional, Dict, Union, Any
from contextlib import asynccontextmanager

import uvicorn
import redis
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from qdrant_client import QdrantClient, models
from qdrant_client.models import SparseVectorParams, Prefetch, Fusion, Document

import json as _json
import time as _time
import uuid as _uuid

# ==========================================
# 🔧 НАСТРОЙКИ
# ==========================================
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HOST = _c("server","host", default="0.0.0.0")
PORT = int(_c("ports","rag_server", default=8091))

QDRANT_URL = f"http://{_c('qdrant','host',default='localhost')}:{_c('ports','qdrant_http',default=6333)}"
COLLECTION_NAME = _c("qdrant","collection", default="allm_docs")

LLAMA_SERVER_URL = f"http://localhost:{_c('ports','llama_server',default=8082)}/v1/chat/completions"
OLLAMA_MODEL = "qwen2.5-0.5b-instruct"
LLM_TIMEOUT = 180

REDIS_HOST = "192.168.10.130"
REDIS_PORT = 6379
REDIS_DB = 3
REDIS_TTL = 600

TOP_K = int(_c("server","top_k", default=10))
MAX_CONTEXT_CHARS = int(_c("server","max_context_chars", default=1500))
MAX_ANSWER_TOKENS = int(_c("server","max_answer_tokens", default=256))

# ==========================================
# 📁 НАСТРОЙКИ INGESTION
# ==========================================
DOCS_DIR = Path("/home/user/allm")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
BATCH_SIZE = 16
SCAN_INTERVAL = 300

IGNORE_DIRS = {
    "venv", ".venv", "env", "__pycache__", "tmp", "temp",
    ".git", ".idea", ".vscode", "node_modules",
    "agent",
    ".dsh",  # скрытая папка с навыками агента — не индексировать
}

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".sh", ".bash", ".php", ".js", ".ts",
    ".json", ".yaml", ".yml", ".html", ".css", ".sql",
    ".xlsx", ".xls", ".docx", ".doc", ".pdf",
}

# Алиасы отделов: сокращение -> полное название
DEPT_ALIASES = {
    "ауо": "АДМИНИСТРАТИВНО - УПРАВЛЕНЧЕСКИЙ ОТДЕЛ",
    "мто": "МАТЕРИАЛЬНО-ТЕХНИЧЕСКИЙ ОТДЕЛ",
    "ит": "ИТ ОТДЕЛ",
    "оп": "ОП",  # префикс для операционных офисов
    "бухгалтерия": "БУХГАЛТЕРИЯ",
    "экономический": "ЭКОНОМИЧЕСКИЙ ОТДЕЛ",
    "юридический": "ЮРИДИЧЕСКИЙ ОТДЕЛ",
    "печатный": "ПЕЧАТНЫЙ ЦЕХ",
    "абонентская": "АБОНЕНТСКАЯ СЛУЖБА",
}

def _expand_department(d: str) -> str:
    """Преобразует аббревиатуру в полное название отдела (если есть алиас)."""
    d_norm = _normalize_text(d).strip()
    return DEPT_ALIASES.get(d_norm, d)

def _department_with_alias(d: str) -> str:
    """Возвращает 'ПОЛНОЕ НАЗВАНИЕ (АЛИАС)' для вывода."""
    d_norm = _normalize_text(d).strip()
    for alias, full in DEPT_ALIASES.items():
        if full == d and len(alias) <= 4:  # короткие алиасы показываем в скобках
            return f"{d} ({alias.upper()})"
    return d


os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("embedding_server")

model: Optional[Any] = None
_sparse_model = None
_dense_model = None
qdrant_client: Optional[QdrantClient] = None
r_client: Optional[redis.Redis] = None

file_hashes: Dict[Path, str] = {}


# ==========================================
# 📝 ПРОМПТЫ
# ==========================================
SYSTEM_PROMPT = """Ты — справочная система. Отвечай на вопрос, используя ТОЛЬКО текст ниже.

ПРАВИЛА:
1. Если в тексте есть ответ — выведи его ДОСЛОВНО, без изменений.
2. Не сокращай и не переформулируй ответ. Копируй как есть.
3. Если ответа в тексте нет — напиши "В справочнике нет такой информации".
4. Не придумывай факты.
5. Отвечай на русском языке.
"""

FEW_SHOT_PROMPT = """Ты — справочная система. Отвечай на вопрос, используя ТОЛЬКО текст ниже.

Пример 1:
Текст:
API_KEY=abc123def456
Вопрос: Какой API_KEY?
Ответ: abc123def456

Пример 2:
Текст:
PASSWORD=secret789
Вопрос: Какой пароль?
Ответ: secret789

Пример 3:
Текст:
USER=admin
Вопрос: Какой USER?
Ответ: admin

Пример 4 (с заголовком чанка):
Текст:
[file.txt | chunk 0]
secret_value_xyz
Вопрос: Какой secret_value?
Ответ: secret_value_xyz

Теперь твой вопрос:
Текст:
{context}

Вопрос: {question}

Ответ:"""


USER_PROMPT_TEMPLATE = """[START_OF_ARCHIVE_DATA]
{context}
[END_OF_ARCHIVE_DATA]

[USER_QUESTION]
Вопрос: {question}

Ответ:"""


# ==========================================
# 📥 INGESTION
# ==========================================

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
    log.debug(f"[extract_text] DOCX {path.name}: {len(text)} символов")
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
    log.debug(f"[extract_text] PDF {path.name}: {len(text)} символов, страниц: {len(reader.pages)}")
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
    log.debug(f"[extract_text] XLSX {path.name}: {len(text)} символов")
    return text



def _extract_docx_table_rows(path: Path) -> List[str]:
    """Извлекает строки таблиц из docx, обогащая их заголовками."""
    import docx
    doc = docx.Document(str(path))
    enriched_rows = []
    
    for table in doc.tables:
        if not table.rows:
            continue
        # Берем заголовки из первой строки
        header_row = table.rows[0]
        headers = [c.text.strip().replace("\n", " ") for c in header_row.cells]
        header_text = " | ".join(headers)
        
        # Обрабатываем остальные строки
        for row in table.rows[1:]:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            # Пропускаем пустые строки
            if not any(cells):
                continue
            row_text = " | ".join(cells)
            # Формируем чанк с заголовками столбцов (если есть)
            if len(headers) == len(cells):
                parts = [f"{h}: {c}" for h, c in zip(headers, cells) if c]
                chunk = f"[{path.name}] " + " | ".join(parts)
            else:
                chunk = f"[{path.name}] {row_text}"
            enriched_rows.append(chunk)
                       
    return enriched_rows


def _extract_pdf_table_rows(path: Path) -> List[str]:
    """Извлекает строки из PDF, где таблица склеена в сплошной текст."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    enriched_rows = []
    
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"

    # Очищаем от HTML-тегов и мусора
    full_text = re.sub(r'<[^>]+>', ' ', full_text)
    full_text = re.sub(r'\s+', ' ', full_text)

    # Ищем паттерны вида: "1Рысов Владимир Владимирович1011001018(863)251-73-54"
    # Номер (1-2 цифры) -> ФИО (3 слова) -> Внут (3 цифры) -> 100 -> Область (3 цифры) -> 8(863)...
    pattern = re.compile(r'(\d{1,2})\s*([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*(\d{3})\s*100\s*(\d{3})\s*(8\(\d{3,4}\)[\d\-]+)')
    
    matches = pattern.findall(full_text)
    for match in matches:
        num, fio, vnut, obl, gorod = match
        chunk = f"[{path.name}] №: {num} | Ф.И.О.: {fio} | Внутренний: {vnut} | Городской: {gorod}"
        enriched_rows.append(chunk)

    return enriched_rows


def _extract_xlsx_table_rows(path: Path) -> List[str]:
    """Извлекает строки таблиц из xlsx, обогащая их заголовками столбцов.

    Поддерживает:
      - склейку нескольких ФИО в одной ячейке (разбивает на отдельные строки);
      - наследование «Отдела»: если в XLSX колонка «Отдел» заполнена только
        у первого сотрудника (merge cells или пустые строки подряд),
        подставляет последнее непустое значение в последующие строки.
    """
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    enriched_rows = []

    for sheet in wb.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        headers = None
        last_dept = ""          # последнее непустое «Отдел»
        last_dept_phone = ""    # последнее непустое «Отдел в тел.»

        for row in rows_iter:
            vals = [str(v).strip().replace("\n", " ") if v is not None else "" for v in row]
            if not any(vals):
                continue
            if headers is None:
                headers = vals
                continue

            # Наследование «Отдела»: если пусто — берём последнее непустое
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
                    found = re.findall(
                        r'[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}',
                        v
                    )
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

    log.debug(f"[_extract_xlsx_table_rows] {path.name}: {len(enriched_rows)} строк")
    return enriched_rows

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    log.debug(f"[extract_text] Файл: {path.name}, расширение: {ext}")

    if ext in {".txt", ".md", ".markdown", ".rst", ".py", ".sh", ".bash",
               ".php", ".js", ".ts", ".json", ".yaml", ".yml",
               ".html", ".css", ".sql"}:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            log.debug(f"[extract_text] Прочитано {len(text)} символов из {path.name}")
            return text
        except Exception as e:
            log.error(f"[extract_text] Ошибка чтения {path.name}: {e}")
            return ""

    if ext == ".docx":
        try:
            # Если в документе есть таблицы, извлекаем их по строкам
            enriched = _extract_docx_table_rows(path)
            if enriched:
                # Возвращаем специальный маркер, чтобы index_file понял, что это готовые чанки
                return "\n---\n".join(enriched)
            else:
                return _extract_docx(path)
        except Exception as e:
            log.error(f"[extract_text] Ошибка DOCX {path.name}: {e}")
            return ""

    if ext == ".pdf":
        try:
            # Сначала пробуем разобрать как таблицу
            enriched = _extract_pdf_table_rows(path)
            if enriched:
                log.debug(f"[extract_text] PDF {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            else:
                return _extract_pdf(path)
        except Exception as e:
            log.error(f"[extract_text] Ошибка PDF {path.name}: {e}")
            return ""

    if ext in {".xlsx", ".xls"}:
        try:
            enriched = _extract_xlsx_table_rows(path)
            if enriched:
                log.debug(f"[extract_text] XLSX {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            else:
                return _extract_xlsx(path)
        except Exception as e:
            log.error(f"[extract_text] Ошибка XLSX {path.name}: {e}")
            return ""

    if ext == ".doc":
        log.warning(f"[extract_text] .doc не поддержан: {path.name}")
        return ""

    log.warning(f"[extract_text] Неизвестное расширение: {ext} ({path.name})")
    return ""


def chunk_text(text: str, max_chars: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    log.debug(f"[chunk_text] Получено {len(chunks)} чанков из {len(text)} символов")
    return chunks


def get_file_hash(path: Path) -> str:
    hasher = hashlib.md5()
    try:
        with open(path, "rb") as f:
            hasher.update(f.read())
        h = hasher.hexdigest()
        log.debug(f"[get_file_hash] {path.name} -> {h[:12]}…")
        return h
    except Exception as e:
        log.error(f"[get_file_hash] Не удалось прочитать {path.name}: {e}")
        return ""


def delete_file_from_index(source_name: str):
    log.info(f"[delete_file_from_index] Удаляю {source_name} из Qdrant...")
    try:
        qdrant_client.delete( # pyright: ignore[reportOptionalMemberAccess]
            collection_name=COLLECTION_NAME,
            points_selector=models.Filter(
                must=[models.FieldCondition(
                    key="source", match=models.MatchValue(value=source_name)
                )]
            ),
        )
        log.info(f"[delete_file_from_index] Успешно удалён {source_name}")
    except Exception as e:
        log.error(f"[delete_file_from_index] Ошибка удаления {source_name}: {e}")


def index_file(path: Path) -> int:
    source_name = path.name
    log.info(f"[index_file] НАЧАЛО индексации: {source_name}")

    text = extract_text(path)
    if not text.strip():
        log.warning(f"[index_file] ПУСТОЙ текст после extract_text: {source_name}")
        return 0

    log.debug(f"[index_file] Текст получен: {len(text)} символов")
    delete_file_from_index(source_name)

    # Если это таблица (маркер ---), режем по строкам, а не по символам
    if ("Таблица: " in text or "№: " in text) and "\n---\n" in text:
        raw_chunks = text.split("\n---\n")
        log.debug(f"[index_file] Таблица обнаружена, разбито на {len(raw_chunks)} строк-чанков")
    else:
        raw_chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        
    if not raw_chunks:
        log.warning(f"[index_file] chunk_text вернул 0 чанков: {source_name}")
        return 0

    prepared_texts = [f"search_document: {ch}" for ch in raw_chunks]

    points = []
    total_batches = (len(prepared_texts) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(prepared_texts), BATCH_SIZE):
        batch_num = i // BATCH_SIZE + 1
        batch_texts = prepared_texts[i : i + BATCH_SIZE]
        batch_raw = raw_chunks[i : i + BATCH_SIZE]
        log.debug(f"[index_file] Батч {batch_num}/{total_batches} ({len(batch_texts)} текстов) для {source_name}")

        try:
            # 1. Dense векторы (fastembed E5)
            dense_texts = [f"passage: {t}" for t in batch_raw]
            dense_vectors = [v.tolist() for v in _dense_model.embed(dense_texts)]
            
            # 2. Sparse векторы (BM25 через fastembed)
            sparse_vectors = list(_sparse_model.embed(batch_raw))
            
            log.debug(f"[index_file] Получено {len(dense_vectors)} dense и {len(sparse_vectors)} sparse векторов")
        except Exception as e:
            log.error(f"[index_file] Ошибка векторизации батча {batch_num} для {source_name}: {e}")
            log.debug(traceback.format_exc())
            continue

        for j, (dense_vec, sparse_emb) in enumerate(zip(dense_vectors, sparse_vectors)):
            chunk_idx = i + j
            chunk_id = hashlib.md5(f"{source_name}_{chunk_idx}".encode()).hexdigest()
            
            # Конвертируем SparseEmbedding (fastembed) в models.SparseVector (qdrant-client)
            sparse_vec = models.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist()
            )
            
            points.append(models.PointStruct(
                id=chunk_id,
                vector={
                    "dense": dense_vec,
                    "sparse": sparse_vec
                },
                payload={
                    "source": source_name,
                    "chunk_index": chunk_idx,
                    "text": batch_raw[j],
                },
            ))

    if points:
        log.debug(f"[index_file] Отправляю {len(points)} точек в Qdrant...")
        try:
            qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points) # pyright: ignore[reportOptionalMemberAccess]
            log.info(f"[index_file] УСПЕХ: {len(points)} чанков для {source_name}")
        except Exception as e:
            log.error(f"[index_file] Ошибка upsert в Qdrant для {source_name}: {e}")
            return 0
    else:
        log.warning(f"[index_file] Нет точек для загрузки: {source_name}")
        return 0

    return len(points)


def scan_docs_dir() -> dict:
    log.debug(f"[scan_docs_dir] Старт прохода. DOCS_DIR={DOCS_DIR}, exists={DOCS_DIR.exists()}, tracked={len(file_hashes)}")

    if not DOCS_DIR.exists():
        log.warning(f"[scan_docs_dir] Папка {DOCS_DIR} не существует. Создаю...")
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        return {"indexed": 0, "deleted": 0, "skipped": 0, "note": "docs_dir_created"}

    current_files: Dict[Path, str] = {}
    for root, dirs, files in os.walk(DOCS_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in ALLOWED_EXTENSIONS:
                current_files[file_path] = get_file_hash(file_path)

    log.debug(f"[scan_docs_dir] Найдено файлов: {len(current_files)} (отслеживается: {len(file_hashes)})")

    indexed, deleted, skipped = 0, 0, 0

    for old_path in list(file_hashes.keys()):
        if old_path not in current_files:
            log.info(f"[scan_docs_dir] ОБНАРУЖЕНО УДАЛЕНИЕ: {old_path.name}")
            delete_file_from_index(old_path.name)
            del file_hashes[old_path]
            deleted += 1

    for path, current_hash in current_files.items():
        is_new = path not in file_hashes
        is_changed = (not is_new) and file_hashes[path] != current_hash
        if is_new or is_changed:
            reason = "НОВЫЙ" if is_new else "ИЗМЕНЁН"
            log.info(f"[scan_docs_dir] ОБНАРУЖЕН {reason} файл: {path.name}")
            n = index_file(path)
            file_hashes[path] = current_hash
            if n > 0:
                indexed += 1
            else:
                skipped += 1
                log.warning(f"[scan_docs_dir] Файл пропущен (0 чанков): {path.name}")

    summary = {
        "indexed": indexed,
        "deleted": deleted,
        "skipped": skipped,
        "total_tracked": len(file_hashes),
    }
    log.debug(f"[scan_docs_dir] Итог прохода: {summary}")
    return summary


async def periodic_scan():
    """Фоновый цикл сканирования (в отдельном потоке, чтобы не блокировать loop)."""
    import asyncio
    log.info(f"[periodic_scan] ЗАПУЩЕН. DOCS_DIR={DOCS_DIR}, интервал={SCAN_INTERVAL}с")
    cycle = 0
    while True:
        cycle += 1
        log.info(f"[periodic_scan] Цикл #{cycle}: старт скана")
        try:
            summary = await asyncio.to_thread(scan_docs_dir)
            log.info(f"[periodic_scan] Цикл #{cycle}: результат {summary}")
        except asyncio.CancelledError:
            log.info("[periodic_scan] Отменён")
            raise
        except Exception as e:
            log.error(f"[periodic_scan] Цикл #{cycle}: ИСКЛЮЧЕНИЕ: {e}")
            log.error(traceback.format_exc())
        try:
            await asyncio.sleep(SCAN_INTERVAL)
        except asyncio.CancelledError:
            log.info("[periodic_scan] Отменён во время сна")
            raise


# ==========================================
# LIFESPAN
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, qdrant_client, r_client
    import asyncio

    log.info("=" * 60)
    log.info("СТАРТ СЕРВЕРА")
    log.info("=" * 60)

    log.info("[lifespan] Подключение к Redis...")
    r_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r_client.ping()
        log.info("[lifespan] Redis OK")
    except Exception as e:
        log.error(f"[lifespan] Redis FAIL: {e}")

    log.info(f"[lifespan] Загрузка Dense-модели (fastembed): {MODEL_NAME}...")
    from fastembed import TextEmbedding
    global _dense_model
    _dense_model = TextEmbedding(model_name=MODEL_NAME)
    
    # Инициализация Sparse-модели BM25 для гибридного поиска
    from fastembed import SparseTextEmbedding
    global _sparse_model
    _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    log.info("[lifespan] Sparse-модель BM25 загружена")
    log.info(f"[lifespan] Dense-модель загружена (размерность 384)")

    log.info("[lifespan] Подключение к Qdrant...")
    qdrant_client = QdrantClient(url=QDRANT_URL)
    try:
        collections = qdrant_client.get_collections().collections
        log.info(f"[lifespan] Qdrant OK, коллекций: {[c.name for c in collections]}")
    except Exception as e:
        log.error(f"[lifespan] Qdrant FAIL: {e}")

    if not qdrant_client.collection_exists(COLLECTION_NAME):
        log.info(f"[lifespan] Создание коллекции {COLLECTION_NAME}...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(size=384, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(modifier=models.Modifier.IDF)
            }
        )
        log.info(f"[lifespan] Коллекция {COLLECTION_NAME} создана")
    else:
        info = qdrant_client.get_collection(COLLECTION_NAME)
        log.info(f"[lifespan] Коллекция {COLLECTION_NAME} существует, точек: {info.points_count}")

    log.info("[lifespan] Запуск фонового сканирования...")
    scan_task = asyncio.create_task(periodic_scan())
    log.info(f"[lifespan] Задача создана: {scan_task}")

    log.info("[lifespan] Вся инфраструктура готова")

    # Прогрев микро-LLM, чтобы первый RAG-запрос не был "холодным"
    try:
        requests.post(
            LLAMA_SERVER_URL,
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=60,
        )
        log.info("[lifespan] Микро-LLM прогрета")
    except Exception as e:
        log.warning(f"[lifespan] Прогрев не удался: {e}")

    yield

    log.info("[lifespan] Остановка сервера...")
    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        log.info("[lifespan] Задача сканирования отменена")
    model = None
    log.info("[lifespan] Сервер остановлен")


app = FastAPI(lifespan=lifespan)


# ==========================================
# СХЕМЫ (с поддержкой content в виде массива)
# ==========================================
class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


class _ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

    @property
    def text(self) -> str:
        """Возвращает текстовое содержимое независимо от формата."""
        if isinstance(self.content, str):
            return self.content
        parts = []
        for item in self.content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)


class _ChatCompletionRequest(BaseModel):
    model: str = "rag"
    messages: List[_ChatMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False


# ==========================================
# RAG PIPELINE (Redis-based)
# ==========================================
def background_rag_pipeline(task_id: str):
    try:
        question = r_client.get(f"task:text:{task_id}")
        if not question:
            log.error(f"[{task_id}] Вопрос не найден в Redis")
            r_client.set(f"task:status:{task_id}", "error", ex=REDIS_TTL)
            return

        r_client.set(f"task:status:{task_id}", "searching", ex=REDIS_TTL)
        log.info(f"[{task_id}] Поиск контекста для: {question}")

        query_vector = list(_dense_model.query_embed(f"query: {question}"))[0].tolist()

        query_filter = None
        file_match = re.search(
            r'[\w.-]+\.(?:md|txt|pdf|docx|xlsx|xls|py|sh|json|ya?ml)',
            question, re.IGNORECASE,
        )
        if file_match:
            detected_source = file_match.group(0)
            log.info(f"[{task_id}] Фильтр по источнику: {detected_source}")
            query_filter = models.Filter(
                must=[models.FieldCondition(
                    key="source", match=models.MatchValue(value=detected_source)
                )]
            )

        hits = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=TOP_K,
            with_payload=True,
        ).points

        if not hits:
            r_client.set(f"task:status:{task_id}", "ok", ex=REDIS_TTL)
            r_client.set(f"task:answer:{task_id}", "В базе данных не найдено релевантных фрагментов.", ex=REDIS_TTL)
            return

        for h in hits:
            log.info(f"[{task_id}]   hit: {h.payload.get('source', '?')} chunk {h.payload.get('chunk_index', '?')} score={h.score:.3f}")

        context_parts, total = [], 0
        for hit in hits:
            src = hit.payload.get("source", "?")
            idx = hit.payload.get("chunk_index", "?")
            text = hit.payload.get("text", "") # pyright: ignore[reportOptionalMemberAccess]
            block = f"[{src} | chunk {idx}]\n{text}\n"
            if total + len(block) > MAX_CONTEXT_CHARS:
                break
            context_parts.append(block)
            total += len(block)

        context = "\n---\n".join(context_parts)
        log.info(f"[{task_id}] Контекст: {len(context_parts)} чанков, {total} символов")

        sources = list(set(h.payload.get("source", "?") for h in hits))
        r_client.set(f"task:sources:{task_id}", ", ".join(sources), ex=REDIS_TTL)

        r_client.set(f"task:status:{task_id}", "generating", ex=REDIS_TTL)
        log.info(f"[{task_id}] Отправка в llama-server...")

        user_prompt = USER_PROMPT_TEMPLATE.format(context=context, question=question)

        resp = requests.post(
            LLAMA_SERVER_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": MAX_ANSWER_TOKENS,
                "temperature": 0.3,
                "top_p": 0.9,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"

        r_client.set(f"task:answer:{task_id}", answer, ex=REDIS_TTL)
        r_client.set(f"task:status:{task_id}", "ok", ex=REDIS_TTL)
        log.info(f"[{task_id}] Задача выполнена")

    except Exception as e:
        log.error(f"Ошибка пайплайна {task_id}: {e}")
        log.error(traceback.format_exc())
        r_client.set(f"task:status:{task_id}", "error", ex=REDIS_TTL)


# ==========================================
# API (родные эндпоинты)
# ==========================================
@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    if not model:
        raise HTTPException(status_code=503, detail="Model not loaded")
    embeddings = [list(_dense_model.embed([f"passage: {t}"]))[0].tolist() for t in request.texts]
    return EmbedResponse(embeddings=embeddings.tolist())


@app.post("/send/{task_id}")
async def send_task(task_id: str, background_tasks: BackgroundTasks):
    if not r_client.exists(f"task:text:{task_id}"):
        raise HTTPException(status_code=404, detail="Task text not found in Redis.")
    background_tasks.add_task(background_rag_pipeline, task_id)
    return {"status": "accepted", "task_id": task_id}


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    status = r_client.get(f"task:status:{task_id}")
    if not status:
        return {"status": "not_found"}
    return {"status": status}


@app.get("/health")
async def health():
    redis_ok = False
    try:
        redis_ok = bool(r_client and r_client.ping())
    except Exception:
        redis_ok = False
    return {
        "status": "ok",
        "model_loaded": _dense_model is not None,
        "qdrant_connected": qdrant_client is not None,
        "redis_connected": redis_ok,
        "docs_dir": str(DOCS_DIR),
        "docs_dir_exists": DOCS_DIR.exists(),
        "tracked_files": len(file_hashes),
    }


@app.post("/scan")
async def trigger_scan():
    log.info("[API /scan] Ручной триггер скана")
    summary = scan_docs_dir()
    return {"status": "ok", "summary": summary}


@app.get("/debug/state")
async def debug_state():
    files_in_dir = []
    if DOCS_DIR.exists():
        for root, dirs, files in os.walk(DOCS_DIR):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for f in files:
                p = Path(root) / f
                files_in_dir.append({
                    "path": str(p),
                    "ext": p.suffix.lower(),
                    "allowed": p.suffix.lower() in ALLOWED_EXTENSIONS,
                    "size": p.stat().st_size if p.exists() else -1,
                })
    return {
        "docs_dir": str(DOCS_DIR),
        "docs_dir_exists": DOCS_DIR.exists(),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "tracked_files_in_memory": {str(k): v[:12] for k, v in file_hashes.items()},
        "files_on_disk": files_in_dir,
        "collection": COLLECTION_NAME,
        "model_dim": model.get_embedding_dimension() if model else None,
    }


# ==========================================
# OpenAI-совместимые эндпоинты
# ==========================================
def _last_user_question(messages: List[_ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user" and m.text.strip():
            return m.text.strip()
    return ""




def _normalize_text(text: str) -> str:
    """Приводит текст к нижнему регистру и заменяет ё на е для поиска."""
    return text.lower().replace('ё', 'е')

def _filter_hits_by_entity(hits, question: str):
    """Фильтрует чанки, оставляя только те, где есть слова с заглавной буквы из вопроса."""
    entity_words = [
        _normalize_text(w) for w in re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question)
        if _normalize_text(w) not in {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая", "какие", "телефон", "директора"}
    ]
    if not entity_words:
        return hits

    # Корень до 5 символов для лучшего покрытия редких фамилий (Жданко -> Жданк)
    stems = []
    for w in entity_words:
        if w.endswith('ко') and len(w) > 5:
            stems.append(w[:-1])  # Жданко -> Жданк
        elif len(w) >= 5:
            stems.append(w[:5])
        elif len(w) >= 4:
            stems.append(w[:4])

    matched = [h for h in hits if any(s in _normalize_text(h.payload.get('text', '')) for s in stems)]
    
    return matched if matched else hits

def _extract_phones_from_text(text: str, question: str = "") -> str:
    """Извлекает телефоны, привязываясь к строке с искомой фамилией и названиям столбцов."""
    lines = text.split('\n')
    
    # Ищем строку, где есть фамилия из вопроса
    target_line = text
    if question:
        entities = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question)
        for entity in entities:
            stem = entity[:-1] if entity.endswith(('а', 'у', 'ым', 'ой')) else entity
            for line in lines:
                if stem.lower() in line.lower():
                    target_line = line
                    break

    # 1. Ищем телефоны, привязанные к названиям столбцов (Внутренний: 101, Мобильный: 8-928...)
    phones = []
    for match in re.finditer(r'(?:Внутренний|Городской|Мобильный|Телефон|Факс|внутренний|городской|мобильный|телефон|факс)\s*[:\-]?\s*([\d\-\(\)\s]{3,20})', target_line):
        val = match.group(1).strip()
        if val:
            phones.append(val)

    # 2. Если не нашли (старая версия таблицы), ищем просто номера
    if not phones:
        phones = re.findall(r'8[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}|\(?\d{4,5}\)?[-\s]?\d{1,3}[-\s]?\d{2}[-\s]?\d{2}|\b\d{3,4}\b', target_line)

    seen = set()
    result = []
    for p in phones:
        p = p.strip()
        if p and p not in seen and len(p) > 2:
            seen.add(p)
            result.append(p)
    return ", ".join(result)


def _collect_all_entity_rows(source_name: str, question: str, limit: int = 200) -> list:
    """Возвращает все чанки источника, где встречается корень сущности из вопроса.
    
    Нужно для мультисовпадений (все «Елены»), когда TOP_K не покрывает всех.
    """
    entities = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question or "")
    IGNORE = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая",
              "какие", "телефон", "директора", "комната", "отдел"}
    entities = [e for e in entities if _normalize_text(e) not in IGNORE]
    if not entities:
        return []

    def _stems_for(e):
        n = _normalize_text(e)
        out = []
        if n.endswith('ко') and len(n) > 5:
            out.append(n[:-1])
        if len(n) >= 5:
            out.append(n[:5])
        if len(n) >= 4:
            out.append(n[:4])
        return out

    all_stems = []
    for e in entities:
        all_stems.extend(_stems_for(e))
    if not all_stems:
        return []

    try:
        scroll_filter = models.Filter(must=[
            models.FieldCondition(key="source", match=models.MatchValue(value=source_name))
        ])
        points, _ = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as e:
        log.warning(f"[_collect_all_entity_rows] scroll failed: {e}")
        return []

    rows = []
    for pt in points:
        text = pt.payload.get("text", "") if pt.payload else ""
        ntext = _normalize_text(text)
        if any(st in ntext for st in all_stems):
            rows.append(text)
    return rows


def _format_department_answer(dept_query: str, all_sources_texts: list) -> str:
    """Формирует таблицу всех сотрудников отдела по запросу «тел <отдел>».

    dept_query — название отдела из вопроса (например, «ИТ», «бухгалтерия»).
    all_sources_texts — список всех чанков источников (строки XLSX).
    Возвращает Markdown-таблицу или "" если отдел не найден.
    """
    def _split_rows(t):
        return [r for r in t.split('\n---\n') if r.strip()]

    pool = []
    for t in all_sources_texts:
        pool.extend(_split_rows(t))

    dq = _normalize_text(dept_query).strip()
    if not dq or len(dq) < 2:
        return ""

    # Ищем строки, где «Отдел» или «Отдел в тел.» содержит запрос
    matched_rows = []
    for row in pool:
        if ':' not in row:
            continue
        # Разбираем поля
        fields = {}
        clean = re.sub(r'^\[[^\]]*\]\s*', '', row)
        for part in clean.split('|'):
            if ':' in part:
                k, v = part.split(':', 1)
                k = k.strip().lower()
                v = v.strip()
                if v:
                    fields[k] = v
        if not fields:
            continue
        # Проверяем «отдел» и «отдел в тел.»
        dept_vals = []
        for k in ('отдел', 'отдел в тел.'):
            if k in fields:
                dept_vals.append(_normalize_text(fields[k]))
        if not dept_vals:
            continue
        # Совпадение по стемам: отрезаем падежные окончания у слов запроса
        # и проверяем, что каждое слово (корень) содержится в значении отдела.
        dq_words = dq.split()
        dq_stems = []
        for w in dq_words:
            if len(w) >= 5:
                dq_stems.append(w[:5])
            elif len(w) >= 4:
                dq_stems.append(w[:4])
            else:
                dq_stems.append(w)
        if not dq_stems:
            continue
        # Проверяем, что все стемы содержатся в хотя бы одном значении отдела
        matched = False
        for dv in dept_vals:
            if all(st in dv for st in dq_stems):
                matched = True
                break
        if matched:
            matched_rows.append(fields)

    if not matched_rows:
        return ""

    # Дедуп по Ф.И.О.
    by_fio = {}
    for f in matched_rows:
        fio = f.get('ф.и.о.') or f.get('фио') or ''
        if fio:
            by_fio[fio] = f
        else:
            by_fio[tuple(sorted(f.items()))] = f

    records = list(by_fio.values())
    if not records:
        return ""

    # Колонки: Ф.И.О., Отдел, Область, Внутренний, Городской
    CANON = {
        '№': '№', 'ф.и.о.': 'Ф.И.О.', 'фио': 'Ф.И.О.',
        'отдел': 'Отдел', 'область': 'Область',
        'внут.': 'Внутренний', 'внутренний': 'Внутренний',
        'городской': 'Городской', 'мобильный': 'Мобильный',
    }
    ORDER = ['№', 'Ф.И.О.', 'Отдел', 'Область', 'Внутренний', 'Городской', 'Мобильный']

    canon_records = []
    for f in records:
        c = {}
        for k, v in f.items():
            ck = CANON.get(k)
            if ck:
                c[ck] = v
        if c.get('Ф.И.О.'):
            canon_records.append(c)

    if not canon_records:
        return ""

    present = set()
    for r in canon_records:
        present.update(r.keys())
    headers = [h for h in ORDER if h in present]

    body_lines = []
    for r in canon_records:
        vals = [r.get(h, '') for h in headers]
        body_lines.append("| " + " | ".join(vals) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, sep] + body_lines)
    result += f"\n\n_Сотрудников в отделе: {len(canon_records)}._"
    return result


def _format_phone_answer_from_hit(hit_text: str, question: str, all_hits_texts=None) -> str:
    """Форматирует ответ в Markdown-таблицу с колонками ФИО, Комната, Отдел, телефоны.

    Поддерживает несколько совпадений (например, несколько «Елен»):
    тогда возвращает таблицу со всеми найденными строками.
    all_hits_texts — список текстов всех hits (для мультисовпадений).
    """
    def _split_rows(t):
        return [r for r in t.split('\n---\n') if r.strip()]

    pool = _split_rows(hit_text)
    if all_hits_texts:
        for t in all_hits_texts:
            if t != hit_text:
                pool.extend(_split_rows(t))

    # Уникализируем
    seen = set()
    uniq_pool = []
    for r in pool:
        key = r.strip()
        if key and key not in seen:
            seen.add(key)
            uniq_pool.append(r)

    # Ключевые слова для поиска совпадений
    entities = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question or "")
    IGNORE = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая",
              "какие", "телефон", "директора", "комната", "отдел"}
    entities = [e for e in entities if _normalize_text(e) not in IGNORE]

    def _stems_for(e):
        n = _normalize_text(e)
        out = []
        if n.endswith('ко') and len(n) > 5:
            out.append(n[:-1])
        if len(n) >= 5:
            out.append(n[:5])
        if len(n) >= 4:
            out.append(n[:4])
        return out

    matches = []
    for row in uniq_pool:
        nrow = _normalize_text(row)
        for e in entities:
            if any(st in nrow for st in _stems_for(e)):
                matches.append(row)
                break

    if not matches:
        return ""

    def _extract_fields(row: str):
        clean = re.sub(r'^\[[^\]]*\]\s*', '', row)
        clean = re.sub(r'\s*---.*$', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        fields = {}
        if ':' in clean:
            for part in clean.split('|'):
                if ':' in part:
                    k, v = part.split(':', 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if v:
                        fields[k] = v
        return fields

    CANON = {
        'фио': 'Ф.И.О.', 'ф.и.о.': 'Ф.И.О.', 'фамилия': 'Ф.И.О.', 'имя': 'Ф.И.О.',
        'комната': 'Комната', 'каб.': 'Комната', 'кабинет': 'Комната',
        'внут.': 'Внутренний', 'внутренний': 'Внутренний', 'телефон внутренний': 'Внутренний',
        'городской': 'Городской', 'телефон городской': 'Городской',
        'мобильный': 'Мобильный', 'телефон мобильный': 'Мобильный',
        'отдел': 'Отдел', 'должность': 'Должность', 'область': 'Область', '№': '№',
    }
    ORDER = ['№', 'Ф.И.О.', 'Должность', 'Комната', 'Отдел', 'Область',
             'Внутренний', 'Городской', 'Мобильный']

    records = []
    for m in matches:
        f = _extract_fields(m)
        canon = {}
        for k, v in f.items():
            ck = CANON.get(k)
            if ck:
                canon[ck] = v
        if canon:
            records.append(canon)

    if not records:
        return ""

    # Дедуп по Ф.И.О.: из нескольких записей с одним ФИО оставляем
    # самую полную (XLSX с «Отдел»/«Область» богаче PDF с 4 полями).
    by_key = {}
    for r in records:
        key = r.get('Ф.И.О.') or tuple(sorted(r.items()))
        if key not in by_key:
            by_key[key] = r
        else:
            # сравниваем по числу непустых полей
            if len([v for v in r.values() if v]) > len([v for v in by_key[key].values() if v]):
                by_key[key] = r
    uniq_records = list(by_key.values())

    present = set()
    for r in uniq_records:
        present.update(r.keys())
    headers = [h for h in ORDER if h in present]
    extra = [h for h in present if h not in headers]
    headers.extend(sorted(extra))
    if not headers:
        return ""

    body_lines = []
    for r in uniq_records:
        vals = [r.get(h, '') for h in headers]
        body_lines.append("| " + " | ".join(vals) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, sep] + body_lines)

    if len(uniq_records) > 1:
        result += "\n\n_Найдено несколько совпадений (" + str(len(uniq_records)) + "). Уточните ФИО, отдел или комнату._"
    return result


def _build_md_table(headers: List[str], values: List[str]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    val_line = "| " + " | ".join(values) + " |"
    return f"{header_line}\n{sep}\n{val_line}"


def _normalize_query_for_search(question: str) -> str:
    """Отрезает падежные окончания у слов с заглавной буквы.

    Особое внимание — фамилиям на -ко (Жданко, Петренко, Шевченко):
    отрезаем конечное 'о', получая устойчивый корень (Жданк-).
    """
    words = question.split()
    result = []
    for w in words:
        if w and w[0].isupper() and len(w) > 4:
            # Фамилии на -ко: Жданко -> Жданк, Петренко -> Петренк
            if w.endswith(('ко', 'КО', 'Ко')) and len(w) > 5:
                w = w[:-1]  # отрезаем только 'о', оставляя 'к'
            elif w.endswith(('а', 'я', 'у', 'ю', 'ой', 'ей', 'ым', 'им', 'ом', 'ем')):
                w = w[:-1]
        result.append(w)
    return " ".join(result)

def _rag_answer(question: str, max_tokens: Optional[int]) -> dict:
    search_question = _normalize_query_for_search(question)
    query_vector = list(_dense_model.query_embed(f"query: {search_question}"))[0].tolist()

    query_filter = None
    file_match = re.search(
        r'[\w.-]+\.(?:md|txt|pdf|docx|xlsx|xls|py|sh|json|ya?ml)',
        question, re.IGNORECASE,
    )
    if file_match:
        query_filter = models.Filter(
            must=[models.FieldCondition(
                key="source", match=models.MatchValue(value=file_match.group(0))
            )]
        )

    # Гибридный поиск
    hits = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=query_vector, using="dense", limit=25),
            Prefetch(query=Document(text=search_question, model="Qdrant/bm25"), using="sparse", limit=25)
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=query_filter,
        limit=TOP_K,
        with_payload=True,
    ).points

    # Фильтрация по ключевым словам (фамилиям)
    hits = _filter_hits_by_entity(hits, question)

    context_parts, total = [], 0
    for hit in hits:
        src_name = hit.payload.get("source", "?")
        idx = hit.payload.get("chunk_index", "?")
        text = hit.payload.get("text", "")
        block = f"[{src_name} | chunk {idx}]\n{text}\n"
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        total += len(block)

    context = "\n---\n".join(context_parts) if context_parts else "(контекст не найден)"
    sources = sorted({h.payload.get("source", "?") for h in hits})

    # --- ПРЯМОЙ ОТВЕТ БЕЗ LLM ---
    # Срабатывает, если есть фамилия (с заглавной) или должность, И есть слово про телефон
    has_name = bool(re.search(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question))
    job_titles = r'директор|секретарь|бухгалтер|начальник|зам|специалист|электроник|инженер|менеджер|руководитель|главный|юрист|экономист|кадровик|делопроизводитель'
    has_job = bool(re.search(job_titles, question, re.IGNORECASE))

    # --- Прямой ответ на «какие отделы есть» ---
    if re.search(r'какие\s+отделы|список\s+отделов|все\s+отделы', question, re.IGNORECASE):
        try:
            all_depts = set()
            offset_d = None
            while True:
                pts_d, offset_d = qdrant_client.scroll(
                    collection_name=COLLECTION_NAME, limit=200, offset=offset_d, with_payload=True
                )
                for pt_d in pts_d:
                    if pt_d.payload and pt_d.payload.get("text"):
                        for row in pt_d.payload["text"].split('\n---\n'):
                            m = re.search(r'Отдел:\s*([^|]+)', row)
                            if m:
                                d = m.group(1).strip()
                                if d:
                                    all_depts.add(d)
                if offset_d is None:
                    break
            # Убираем мусор
            all_depts = {d for d in all_depts if _normalize_text(d) not in {'отдел', 'отдел в тел.', ''}}
            if all_depts:
                result = "В справочнике есть отделы:\n" + "\n".join(f"- {_department_with_alias(d)}" for d in sorted(all_depts))
                log.info(f"[rag] Прямой ответ (список отделов): {len(all_depts)} отделов")
                return {"answer": result, "sources": sources, "hits": len(hits), "no_llm": True}
        except Exception as e:
            log.warning(f"[rag] list departments failed: {e}")
    # --- КОНЕЦ ПРЯМОГО ОТВЕТА (список отделов) ---

    # --- Прямой ответ по ОТДЕЛУ (тел ИТ, тел бухгалтерия и т.п.) ---
    if re.search(r'телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт|кто\s+работает|кто\s+сотрудник|список\s+сотрудник|сотрудник|люди|людей|человек|сколько|количество|кол-во|как\s+много|кто\s+в\s+отдел', question, re.IGNORECASE):
        # Убираем служебные слова, чтобы получить название отдела
        dept_query = re.sub(
            r'\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|людей|человек|в|на|по|сколько|количество|кол-во|как|много)\b',
            ' ', question, flags=re.IGNORECASE
        ).strip()
        # Убираем лишние пробелы и знаки
        dept_query = re.sub(r'\s+', ' ', dept_query).strip(' .,!?-')
        if dept_query and len(dept_query) >= 2:
            # Собираем все источники (XLSX + PDF) для поиска по отделу
            try:
                all_src_texts = []
                offset = None
                while True:
                    pts, offset = qdrant_client.scroll(
                        collection_name=COLLECTION_NAME,
                        limit=200, offset=offset, with_payload=True,
                    )
                    for pt in pts:
                        if pt.payload and pt.payload.get("text"):
                            all_src_texts.append(pt.payload["text"])
                    if offset is None:
                        break
                dept_table = _format_department_answer(_expand_department(dept_query), all_src_texts)
                if dept_table:
                    log.info(f"[rag] Прямой ответ по отделу «{dept_query}»:\n{dept_table[:200]}")
                    return {"answer": dept_table, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as e:
                log.warning(f"[rag] dept answer failed: {e}")
    # --- КОНЕЦ ПРЯМОГО ОТВЕТА ПО ОТДЕЛУ ---

    # --- Прямой ответ на «в каком отделе <Фамилия>» / «где сидит» ---
    if re.search(r'отдел|комнат|кабинет|где\s+сидит|где\s+работает', question, re.IGNORECASE):
        ent_words = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question)
        IGNORE_ATTR = {'каком', 'какой', 'какая', 'какие', 'отдел', 'отделе',
                       'комната', 'комнате', 'кабинет', 'кабинете', 'где', 'сидит',
                       'работает', 'телефон'}
        ent_words = [w for w in ent_words if _normalize_text(w) not in IGNORE_ATTR]
        if ent_words:
            try:
                all_src_texts = []
                offset = None
                while True:
                    pts, offset = qdrant_client.scroll(
                        collection_name=COLLECTION_NAME,
                        limit=200, offset=offset, with_payload=True,
                    )
                    for pt in pts:
                        if pt.payload and pt.payload.get("text"):
                            all_src_texts.append(pt.payload["text"])
                    if offset is None:
                        break
                found_rows = []
                for t in all_src_texts:
                    for row in t.split('\n---\n'):
                        if ':' not in row:
                            continue
                        norm_row = _normalize_text(row)
                        for e in ent_words:
                            n = _normalize_text(e)
                            stems = []
                            if n.endswith('ко') and len(n) > 5:
                                stems.append(n[:-1])
                            if len(n) >= 5:
                                stems.append(n[:5])
                            if len(n) >= 4:
                                stems.append(n[:4])
                            if any(st in norm_row for st in stems):
                                found_rows.append(row)
                                break
                seen = set()
                uniq = []
                for r in found_rows:
                    k = r.strip()
                    if k and k not in seen:
                        seen.add(k)
                        uniq.append(r)
                if uniq:
                    formatted = _format_phone_answer_from_hit(uniq[0], question, all_hits_texts=uniq)
                    if formatted:
                        log.info(f"[rag] Прямой ответ атрибута:\n{formatted}")
                        return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as e:
                log.warning(f"[rag] attr answer failed: {e}")
    # --- КОНЕЦ ПРЯМОГО ОТВЕТА АТРИБУТА ---

    if (has_name or has_job) and re.search(r'телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт', question, re.IGNORECASE):
        all_texts = [h.payload.get('text', '') for h in hits]
        # Собираем ВСЕ источники из hits и из Qdrant (на случай, если поиск поднял PDF)
        sources_in_hits = sorted({h.payload.get('source', '') for h in hits if h.payload.get('source')})
        extra_rows = []
        for sn in sources_in_hits:
            extra_rows.extend(_collect_all_entity_rows(sn, question))
        # Также пробуем найти по всем источникам, если в hits нет XLSX
        try:
            all_sources = set()
            offset = None
            while True:
                pts, offset = qdrant_client.scroll(collection_name=COLLECTION_NAME, limit=200, offset=offset, with_payload=True)
                for pt in pts:
                    if pt.payload and pt.payload.get("source"):
                        all_sources.add(pt.payload["source"])
                if offset is None:
                    break
            for sn in sorted(all_sources):
                if sn not in sources_in_hits:
                    extra_rows.extend(_collect_all_entity_rows(sn, question))
        except Exception as e:
            log.warning(f"[rag] scroll all sources failed: {e}")
        combined_texts = list(dict.fromkeys(all_texts + extra_rows))
        # Пробуем прямой ответ по каждому тексту из combined (без проверки matched)
        for t in combined_texts:
            formatted = _format_phone_answer_from_hit(t, question, all_hits_texts=combined_texts)
            if formatted:
                log.info(f"[rag] Прямой ответ без LLM:\n{formatted}")
                return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}
    # --- КОНЕЦ ПРЯМОГО ОТВЕТА ---

    # === ДОБАВЛЕНИЕ ТАБЛИЦЫ ОТДЕЛА В КОНТЕКСТ (для LLM) ===
    dept_query_for_llm = re.sub(
        r'\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|в|на|по)\b',
        ' ', question, flags=re.IGNORECASE
    ).strip()
    if dept_query_for_llm and len(dept_query_for_llm) >= 2:
        all_texts_for_llm = []
        offset_llm = None
        while True:
            pts_llm, offset_llm = qdrant_client.scroll(
                collection_name=COLLECTION_NAME, limit=200, offset=offset_llm, with_payload=True
            )
            for pt_llm in pts_llm:
                if pt_llm.payload and pt_llm.payload.get("text"):
                    all_texts_for_llm.append(pt_llm.payload["text"])
            if offset_llm is None:
                break
        dept_table_for_llm = _format_department_answer(dept_query_for_llm, all_texts_for_llm)
        if dept_table_for_llm:
            extra_llm = "\n---\nТаблица сотрудников отдела:\n" + dept_table_for_llm + "\n"
            if len(context) + len(extra_llm) <= MAX_CONTEXT_CHARS + 1000:
                context += extra_llm
                log.info(f"[RAG] Добавлена таблица отдела {dept_query_for_llm} в контекст для LLM")
    # === КОНЕЦ ===

    # Выбор промпта: few-shot для запросов про теги/ключи, обычный — для остальных
    _tag_re = r'\b(токен|токен[а-я]*|ключ|пароль|api[_ ]?key|hf_|secret)\b'
    if re.search(_tag_re, question, re.IGNORECASE) or re.search(r'\b\w+_\w+\b', question):
        _prompt_to_use = FEW_SHOT_PROMPT
        log.info(f"[rag] Используется FEW_SHOT_PROMPT для вопроса: {question!r}")
    else:
        _prompt_to_use = SYSTEM_PROMPT
    user_prompt = _prompt_to_use.format(context=context, question=question)

    resp = requests.post(
        LLAMA_SERVER_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or MAX_ANSWER_TOKENS,
            "temperature": 0.3,
            "top_p": 0.9,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=LLM_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"
    
    # Постобработка отключена: _extract_phones_from_text выдёргивал
    # случайные числа из чанка (№ строки, внут., код города) и давал мусор.
    # Если прямой ответ не сработал — доверяем LLM.

    return {"answer": answer, "sources": sources, "hits": len(hits)}

@app.post("/v1/chat/completions")
async def openai_chat_completions(req: _ChatCompletionRequest):
    question = _last_user_question(req.messages)
    if not question:
        raise HTTPException(status_code=400, detail="No user message found")

    try:
        result = _rag_answer(question, req.max_tokens)
    except Exception as e:
        log.error(f"[openai] RAG error: {e}")
        log.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"RAG error: {e}")

    answer = result["answer"]
    created = int(_time.time())
    completion_id = f"chatcmpl-{_uuid.uuid4().hex[:24]}"

    if req.stream:
        async def event_gen():
            first = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }],
            }
            yield f"data: {_json.dumps(first, ensure_ascii=False)}\n\n"
            for i in range(0, len(answer), 40):
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": answer[i:i+40]},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
            last = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            }
            yield f"data: {_json.dumps(last, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    prompt_tokens = len(question) // 4
    completion_tokens = len(answer) // 4
    return JSONResponse({
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "x_rag_sources": result["sources"],
        "x_rag_hits": result["hits"],
    })


HTML_INDEX = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAG · Телефонный справочник</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0; background: #f4f5f7; color: #1a1a1a; }
  header { background: #1f2937; color: #fff; padding: 12px 20px;
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 18px; font-weight: 600; }
  header .status { font-size: 12px; opacity: 0.85; }
  header .status .dot { display: inline-block; width: 8px; height: 8px;
                        border-radius: 50%; background: #ef4444; margin-right: 4px; }
  header .status.ok .dot { background: #22c55e; }
  main { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .chat { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          display: flex; flex-direction: column; height: calc(100vh - 160px); }
  .messages { flex: 1; overflow-y: auto; padding: 16px; }
  .msg { margin-bottom: 12px; padding: 10px 14px; border-radius: 10px;
         max-width: 90%; white-space: pre-wrap; word-wrap: break-word; }
  .msg.user { background: #dbeafe; margin-left: auto; }
  .msg.assistant { background: #f3f4f6; }
  .msg.assistant table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  .msg.assistant th, .msg.assistant td { border: 1px solid #d1d5db; padding: 4px 8px; text-align: left; }
  .msg.assistant th { background: #e5e7eb; }
  .msg.assistant em { color: #6b7280; }
  .input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; }
  .input-row textarea { flex: 1; resize: none; border: 1px solid #d1d5db;
                        border-radius: 8px; padding: 8px 12px; font-size: 14px;
                        font-family: inherit; min-height: 44px; max-height: 120px; }
  .input-row button { background: #2563eb; color: #fff; border: 0; border-radius: 8px;
                      padding: 0 20px; font-size: 14px; cursor: pointer; font-weight: 500; }
  .input-row button:disabled { background: #93c5fd; cursor: not-allowed; }
  .tools { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .tools button { background: #fff; border: 1px solid #d1d5db; border-radius: 8px;
                  padding: 6px 12px; font-size: 13px; cursor: pointer; }
  .tools button:hover { background: #f9fafb; }
  .hint { font-size: 12px; color: #6b7280; margin-top: 6px; }
  .sources { font-size: 11px; color: #6b7280; margin-top: 6px; }
</style>
</head>
<body>
<header>
  <h1>📞 RAG · Телефонный справочник</h1>
  <div class="status" id="status"><span class="dot"></span>проверка...</div>
</header>
<main>
  <div class="chat">
    <div class="messages" id="messages">
      <div class="msg assistant">
        👋 <b>Привет! Я — справочная система.</b><br><br>
        <b>Что можно спросить:</b><br>
        • <b>Телефон по фамилии:</b> «тел Жданко», «телефон Мельникова»<br>
        • <b>Телефон по отделу:</b> «тел ИТ», «тел АУО», «тел МТО»<br>
        • <b>Список сотрудников:</b> «Кто работает в ИТ отделе», «Сколько людей в бухгалтерии»<br>
        • <b>Отдел сотрудника:</b> «в каком отделе Дуванский»<br>
        • <b>Список отделов:</b> «Какие отделы есть?»<br>
        • <b>Токены/ключи:</b> «Какой токен HF?»<br><br>
        <i>Начните с вопроса «Какие отделы есть?», чтобы увидеть все отделы.</i>
      </div>
    </div>
    <div class="input-row">
      <textarea id="input" placeholder="Например: тел Жданко, тел ИТ, какие отделы есть?" rows="1"></textarea>
      <button id="send">Отправить</button>
    </div>
  </div>
  <div class="tools">
    <button onclick="doHealth()">🏥 Здоровье</button>
    <button onclick="doScan()">🔄 Сканировать</button>
    <button onclick="doReindex()">📥 Переиндексировать XLSX</button>
    <span class="hint" id="hint"></span>
  </div>
</main>
<script>
(function () {
  var messagesEl = document.getElementById('messages');
  var inputEl = document.getElementById('input');
  var sendEl = document.getElementById('send');
  var statusEl = document.getElementById('status');
  var hintEl = document.getElementById('hint');

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Markdown-таблица | a | b | ... → HTML-таблица
  function renderMarkdown(text) {
    var lines = String(text == null ? '' : text).split(String.fromCharCode(10));
    var out = [];
    var inTable = false;
    var inList = false;
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      var trimmed = line.trim();

      // Таблицы
      if (trimmed.charAt(0) === '|' && trimmed.charAt(trimmed.length - 1) === '|') {
        if (inList) { out.push('</ul>'); inList = false; }
        var next = (i + 1 < lines.length) ? lines[i + 1] : '';
        if (!inTable && next.indexOf('---') !== -1) {
          inTable = true;
          out.push('<table><thead><tr>');
          var cells0 = trimmed.split('|').slice(1, -1);
          for (var k = 0; k < cells0.length; k++) {
            out.push('<th>' + esc(cells0[k].trim()) + '</th>');
          }
          out.push('</tr></thead><tbody>');
          i += 2;
          continue;
        } else if (inTable) {
          var cells = trimmed.split('|').slice(1, -1);
          out.push('<tr>');
          for (var j = 0; j < cells.length; j++) {
            out.push('<td>' + esc(cells[j].trim()) + '</td>');
          }
          out.push('</tr>');
          i += 1;
          continue;
        }
      } else if (inTable) {
        out.push('</tbody></table>');
        inTable = false;
      }

      // Маркированные списки: "- пункт" или "• пункт"
      var isListItem = (trimmed.indexOf('- ') === 0) || (trimmed.indexOf('• ') === 0) || (trimmed.indexOf('* ') === 0);
      if (isListItem) {
        if (!inList) {
          out.push('<ul>');
          inList = true;
        }
        var itemText = trimmed.replace(/^[-•*]\s+/, '');
        out.push('<li>' + esc(itemText) + '</li>');
        i += 1;
        continue;
      } else if (inList) {
        out.push('</ul>');
        inList = false;
      }

      // Обычный текст
      if (trimmed === '') {
        out.push('<br>');
      } else if (trimmed.charAt(0) === '_' && trimmed.charAt(trimmed.length - 1) === '_') {
        out.push('<em>' + esc(trimmed.slice(1, -1)) + '</em>');
      } else {
        out.push(esc(line));
      }
      i += 1;
    }
    if (inTable) out.push('</tbody></table>');
    if (inList) out.push('</ul>');
    return out.join('');
  }

  function addMessage(role, text, sources) {
    var div = document.createElement('div');
    div.className = 'msg ' + role;
    if (role === 'assistant') {
      div.innerHTML = renderMarkdown(text);
      if (sources && sources.length) {
        var sEl = document.createElement('div');
        sEl.className = 'sources';
        sEl.textContent = 'Источники: ' + sources.join(', ');
        div.appendChild(sEl);
      }
    } else {
      div.textContent = text;
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function send() {
    var q = inputEl.value.trim();
    if (!q) return;
    addMessage('user', q);
    inputEl.value = '';
    sendEl.disabled = true;
    hintEl.textContent = 'думаю...';
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: 'rag', messages: [{role: 'user', content: q}]})
    }).then(function (r) { return r.json(); }).then(function (d) {
      var ans = (d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content) || '(пусто)';
      addMessage('assistant', ans, d.x_rag_sources || []);
      var t1 = (window.performance && performance.now) ? performance.now() : Date.now();
      hintEl.textContent = ((t1 - t0) / 1000).toFixed(2) + ' с';
    }).catch(function (e) {
      addMessage('assistant', 'Ошибка: ' + e.message);
      hintEl.textContent = '';
    }).then(function () {
      sendEl.disabled = false;
    });
  }

  function doHealth() {
    hintEl.textContent = 'health...';
    fetch('/health').then(function (r) { return r.json(); }).then(function (d) {
      addMessage('assistant', 'health:\n' + JSON.stringify(d, null, 2));
      hintEl.textContent = '';
    }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function doScan() {
    hintEl.textContent = 'scan...';
    fetch('/scan', {method: 'POST'}).then(function (r) { return r.json(); }).then(function (d) {
      addMessage('assistant', 'scan:\n' + JSON.stringify(d, null, 2));
      hintEl.textContent = '';
    }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function doReindex() {
    var name = prompt('Имя файла (source):', 'Телефонный справочник.xlsx');
    if (!name) return;
    hintEl.textContent = 'reindex...';
    fetch('/reindex/' + encodeURIComponent(name), {method: 'POST'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        addMessage('assistant', 'reindex:\n' + JSON.stringify(d, null, 2));
        hintEl.textContent = '';
      }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function checkStatus() {
    fetch('/health', {cache: 'no-store'}).then(function (r) { return r.json(); }).then(function (d) {
      if (d.status === 'ok' && d.model_loaded) {
        statusEl.className = 'status ok';
        statusEl.innerHTML = '<span class="dot"></span>онлайн · модель загружена';
      } else {
        statusEl.className = 'status';
        statusEl.innerHTML = '<span class="dot"></span>деградация';
      }
    }).catch(function (e) {
      statusEl.className = 'status';
      statusEl.innerHTML = '<span class="dot"></span>offline';
    });
  }

  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  window.doHealth = doHealth;
  window.doScan = doScan;
  window.doReindex = doReindex;

  checkStatus();
  setInterval(checkStatus, 10000);
})();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def ui_index():
    return HTML_INDEX


@app.get("/v1/models")
async def openai_models():
    return {
        "object": "list",
        "data": [{
            "id": "rag",
            "object": "model",
            "created": int(_time.time()),
            "owned_by": "local-rag",
        }],
    }


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, timeout_graceful_shutdown=5)
