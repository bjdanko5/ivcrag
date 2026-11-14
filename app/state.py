"""Shared application configuration and runtime state."""
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import redis
import requests
from qdrant_client import QdrantClient, models
from qdrant_client.models import Document, Prefetch

from . import config

os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

state = SimpleNamespace(
    log=logging.getLogger("embedding_server"),
    model=None,
    _sparse_model=None,
    _dense_model=None,
    qdrant_client=None,
    r_client=None,
    file_hashes={},
    models=models,
    Document=Document,
    Prefetch=Prefetch,
    requests=requests,
)

__all__ = ["config", "state"]
