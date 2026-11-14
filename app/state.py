"""Application state and shared runtime dependencies."""
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import redis
import requests
from qdrant_client import QdrantClient, models
from qdrant_client.models import Document, Prefetch

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
    "log", "model", "_sparse_model", "_dense_model", "qdrant_client",
    "r_client", "file_hashes", "models", "Document", "Prefetch", "requests",
]
