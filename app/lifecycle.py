"""Application lifespan: initialize dependencies and background scanning."""
import asyncio
from contextlib import asynccontextmanager

import redis
import requests
from fastapi import FastAPI
from qdrant_client import QdrantClient, models
from qdrant_client.models import SparseVectorParams

from app.state import config, state
from app.ingestion.scanner import _load_hashes, periodic_scan


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.log.info("=" * 60)
    state.log.info("СТАРТ СЕРВЕРА")
    state.log.info("=" * 60)

    state.log.info("[lifespan] Подключение к Redis...")
    state.r_client = redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        decode_responses=True,
    )
    try:
        state.r_client.ping()
        state.log.info("[lifespan] Redis OK")
    except Exception as exc:
        state.log.error(f"[lifespan] Redis FAIL: {exc}")

    state.log.info(f"[lifespan] Загрузка Dense-модели (fastembed): {config.MODEL_NAME}...")
    from fastembed import TextEmbedding
    state._dense_model = TextEmbedding(model_name=config.MODEL_NAME)

    from fastembed import SparseTextEmbedding
    state._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    state.log.info("[lifespan] Sparse-модель BM25 загружена")
    state.log.info("[lifespan] Dense-модель загружена (размерность 384)")

    state.log.info("[lifespan] Подключение к Qdrant...")
    state.qdrant_client = QdrantClient(url=config.QDRANT_URL)
    try:
        collections = state.qdrant_client.get_collections().collections
        state.log.info(f"[lifespan] Qdrant OK, коллекций: {[c.name for c in collections]}")
    except Exception as exc:
        state.log.error(f"[lifespan] Qdrant FAIL: {exc}")

    if not state.qdrant_client.collection_exists(config.COLLECTION_NAME):
        state.log.info(f"[lifespan] Создание коллекции {config.COLLECTION_NAME}...")
        state.qdrant_client.create_collection(
            collection_name=config.COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(size=384, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        state.log.info(f"[lifespan] Коллекция {config.COLLECTION_NAME} создана")
    else:
        info = state.qdrant_client.get_collection(config.COLLECTION_NAME)
        state.log.info(
            f"[lifespan] Коллекция {config.COLLECTION_NAME} существует, точек: {info.points_count}"
        )

    state.log.info("[lifespan] Запуск фонового сканирования...")
    if config.SCAN_REINDEX_ON_START:
        state.log.info("[lifespan] reindex_on_start=true — file_hashes сбрасываются (переиндексация всех)")
        state.file_hashes.clear()
    else:
        _load_hashes()
    scan_task = asyncio.create_task(periodic_scan())
    state.log.info(f"[lifespan] Задача создана: {scan_task}")
    state.log.info("[lifespan] Вся инфраструктура готова")

    try:
        requests.post(
            config.LLM_URL,
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=60,
        )
        state.log.info(f"[lifespan] LLM прогрета ({config.LLM_MODE}: {config.LLM_MODEL})")
    except Exception as exc:
        state.log.warning(f"[lifespan] Прогрев не удался: {exc}")

    yield

    state.log.info("[lifespan] Остановка сервера...")
    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        state.log.info("[lifespan] Задача сканирования отменена")
    state.model = None
    state.log.info("[lifespan] Сервер остановлен")


__all__ = ["lifespan"]
