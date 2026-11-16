import os as _os
try:
    import yaml as _yaml
    _CFG_PATH = _os.environ.get("IVCRAG_CFG", "/home/user/ivcrag/config.yaml")
    _CFG = _yaml.safe_load(open(_CFG_PATH, encoding="utf-8")) or {}
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

import os
import re
from pathlib import Path

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HOST = _c("server", "host", default="0.0.0.0")
PORT = int(_c("ports", "rag_server", default=8091))

QDRANT_URL = f"http://{_c('qdrant', 'host', default='localhost')}:{_c('ports', 'qdrant_http', default=6333)}"
COLLECTION_NAME = _c("qdrant", "collection", default="allm_docs")

# --- LLM: локальная (llama.cpp) или внешняя (OpenAI-совместимая) ---
LLM_MODE = _c("llm", "mode", default="local")
LLM_TIMEOUT = int(_c("llm", "timeout", default=180))
LLM_API_KEY = _c("llm", "api_key", default="") or ""
LLM_FALLBACK_TO_LOCAL = bool(_c("llm", "fallback_to_local", default=True))

LLM_LOCAL_URL = _c(
    "llm", "local", "url",
    default=f"http://localhost:{_c('ports', 'llama_server', default=8082)}/v1/chat/completions",
)
LLM_LOCAL_MODEL = _c(
    "llm", "local", "model",
    default=_c("models", "llm_gguf", default="qwen2.5-1.5b-instruct-q4_k_m.gguf"),
)

LLM_REMOTE_URL = _c("llm", "remote", "url", default="")
LLM_REMOTE_MODEL = _c("llm", "remote", "model", default="")

if LLM_MODE == "remote" and LLM_REMOTE_URL:
    LLM_URL = LLM_REMOTE_URL
    LLM_MODEL = LLM_REMOTE_MODEL
else:
    LLM_URL = LLM_LOCAL_URL
    LLM_MODEL = LLM_LOCAL_MODEL

# Обратная совместимость (используется в health и прогреве)
LLAMA_SERVER_URL = LLM_LOCAL_URL
OLLAMA_MODEL = LLM_MODEL

REDIS_HOST = "192.168.10.130"
REDIS_PORT = 6379
REDIS_DB = 3
REDIS_TTL = 600

TOP_K = int(_c("server", "top_k", default=10))
MAX_CONTEXT_CHARS = int(_c("server", "max_context_chars", default=1500))
MAX_ANSWER_TOKENS = int(_c("server", "max_answer_tokens", default=256))

DOCS_DIR = Path("/home/user/allm")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
BATCH_SIZE = 16
SCAN_METHOD = _c("scan", "method", default="mtime")
SCAN_PERSIST = bool(_c("scan", "persist", default=True))
SCAN_REINDEX_ON_START = bool(_c("scan", "reindex_on_start", default=False))
SCAN_HASHES_FILE = Path(_c("scan", "hashes_file", default=str(Path.home() / "ivcrag" / "data" / "hashes.json")))
SCAN_INTERVAL = int(_c("scan", "interval", default=300))

IGNORE_DIRS = {
    "venv", ".venv", "env", "__pycache__", "tmp", "temp",
    ".git", ".idea", ".vscode", "node_modules",
    "agent", ".dsh",
}

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".sh", ".bash", ".php", ".js", ".ts",
    ".json", ".yaml", ".yml", ".html", ".css", ".sql",
    ".xlsx", ".xls", ".docx", ".doc", ".pdf",
}

DEPT_ALIASES = {
    "ауо": "АДМИНИСТРАТИВНО - УПРАВЛЕНЧЕСКИЙ ОТДЕЛ",
    "мто": "МАТЕРИАЛЬНО-ТЕХНИЧЕСКИЙ ОТДЕЛ",
    "ит": "ИТ ОТДЕЛ",
    "оп": "ОП",
    "бухгалтерия": "БУХГАЛТЕРИЯ",
    "экономический": "ЭКОНОМИЧЕСКИЙ ОТДЕЛ",
    "юридический": "ЮРИДИЧЕСКИЙ ОТДЕЛ",
    "печатный": "ПЕЧАТНЫЙ ЦЕХ",
    "абонентская": "АБОНЕНТСКАЯ СЛУЖБА",
}

SYSTEM_PROMPT = """Ты — справочная система. Отвечай на вопрос, используя ТОЛЬКО текст ниже.

ПРАВИЛА:
1. Если в тексте есть ПРЯМОЙ ответ — выведи его как есть (дословно).
2. Если прямого ответа нет, но ответ МОЖНО ВЫВЕСТИ из текста (таблица, список, определение, перечисление) — сформулируй краткий ответ на основе текста.
3. Если в тексте вообще нет информации по вопросу — напиши "В справочнике нет такой информации".
4. Не придумывай факты, которых нет в тексте.
5. Отвечай на русском языке.

Текст:
{context}

Вопрос: {question}

Ответ:"""

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


def _expand_department(d: str) -> str:
    """Преобразует аббревиатуру в полное название отдела (если есть алиас)."""
    d_norm = _normalize_text(d).strip()
    return DEPT_ALIASES.get(d_norm, d)


def _department_with_alias(d: str) -> str:
    """Возвращает 'ПОЛНОЕ НАЗВАНИЕ (АЛИАС)' для вывода."""
    d_norm = _normalize_text(d).strip()
    for alias, full in DEPT_ALIASES.items():
        if full == d and len(alias) <= 4:
            return f"{d} ({alias.upper()})"
    return d


def _normalize_text(text: str) -> str:
    """Приводит текст к нижнему регистру и заменяет ё на е для поиска."""
    return text.lower().replace('ё', 'е')


# compatibility for old imports
__all__ = [
    "MODEL_NAME",
    "HOST",
    "PORT",
    "QDRANT_URL",
    "COLLECTION_NAME",
    "LLAMA_SERVER_URL",
    "OLLAMA_MODEL",
    "LLM_TIMEOUT",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_TTL",
    "TOP_K",
    "MAX_CONTEXT_CHARS",
    "MAX_ANSWER_TOKENS",
    "DOCS_DIR",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "BATCH_SIZE",
    "SCAN_METHOD",
    "SCAN_PERSIST",
    "SCAN_REINDEX_ON_START",
    "SCAN_HASHES_FILE",
    "SCAN_INTERVAL",
    "IGNORE_DIRS",
    "ALLOWED_EXTENSIONS",
    "DEPT_ALIASES",
    "SYSTEM_PROMPT",
    "FEW_SHOT_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "_expand_department",
    "_department_with_alias",
    "_normalize_text",
    "LLM_URL",
    "LLM_MODEL",
    "LLM_MODE",
    "LLM_LOCAL_URL",
    "LLM_LOCAL_MODEL",
    "LLM_REMOTE_URL",
    "LLM_REMOTE_MODEL",
    "LLM_API_KEY",
    "LLM_FALLBACK_TO_LOCAL",
]
