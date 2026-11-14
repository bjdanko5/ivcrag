import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import redis
from qdrant_client import QdrantClient

from config import (
    HOST,
    PORT,
    QDRANT_URL,
    COLLECTION_NAME,
    LLAMA_SERVER_URL,
    OLLAMA_MODEL,
    LLM_TIMEOUT,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_TTL,
    DOCS_DIR,
    SCAN_REINDEX_ON_START,
    SCAN_INTERVAL,
    MODEL_NAME,
    TOP_K,
    MAX_CONTEXT_CHARS,
    MAX_ANSWER_TOKENS,
    SCAN_PERSIST,
    SCAN_HASHES_FILE,
)

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

__all__ = [
    "log",
    "model",
    "_sparse_model",
    "_dense_model",
    "qdrant_client",
    "r_client",
    "file_hashes",
]
