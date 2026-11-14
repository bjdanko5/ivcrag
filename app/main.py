"""Application lifecycle for startup and shutdown."""
import asyncio
import logging

from fastapi import FastAPI

try:
    import app.config as config
    import app.state as state
except ImportError:  # pragma: no cover
    import config
    import state

log = logging.getLogger("embedding_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, qdrant_client, r_client
    import asyncio

    log.info("=" * 60)
    log.info("СТАРТ СЕРВЕРА")
    log.info("=" * 60)

    log.info("[lifespan] Подключение к Redis...")
    state.r_client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB, decode_responses=True)
    try:
        state.r_client.ping()
        log.info("[lifespan] Redis OK")
    except Exception as exc:
        log.error(f"[lifespan] Redis FAIL: {exc}")

    log.info(f"[lifespan] Загрузка Dense-модели (fastembed): {config.MODEL_NAME}...")
    from fastembed import TextEmbedding
    state._dense_model = TextEmbedding(model_name=config.MODEL_NAME)

    from fastembed import SparseTextEmbedding
    state._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    log.info("[lifespan] Sparse-модель BM25 загружена")
    log.info(f"[lifespan] Dense-модель загружена (размерность 384)")

    log.info("[lifespan] Подключение к Qdrant...")
    state.qdrant_client = QdrantClient(url=config.QDRANT_URL)
    try:
        collections = state.qdrant_client.get_collections().collections
        log.info(f"[lifespan] Qdrant OK, коллекций: {[c.name for c in collections]}")
    except Exception as exc:
        log.error(f"[lifespan] Qdrant FAIL: {exc}")

    if not state.qdrant_client.collection_exists(config.COLLECTION_NAME):
        log.info(f"[lifespan] Создание коллекции {config.COLLECTION_NAME}...")
        state.qdrant_client.create_collection(
            collection_name=config.COLLECTION_NAME,
            vectors_config={"dense": models.VectorParams(size=384, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        log.info(f"[lifespan] Коллекция {config.COLLECTION_NAME} создана")
    else:
        info = state.qdrant_client.get_collection(config.COLLECTION_NAME)
        log.info(f"[lifespan] Коллекция {config.COLLECTION_NAME} существует, точек: {info.points_count}")

    log.info("[lifespan] Запуск фонового сканирования...")
    if config.SCAN_REINDEX_ON_START:
        log.info("[lifespan] reindex_on_start=true — file_hashes сбрасываются (переиндексация всех)")
        state.file_hashes.clear()
    else:
        from app.ingestion.scanner import _load_hashes
        _load_hashes()
    scan_task = asyncio.create_task(periodic_scan())
    log.info(f"[lifespan] Задача создана: {scan_task}")

    log.info("[lifespan] Вся инфраструктура готова")

    try:
        requests.post(
            config.LLAMA_SERVER_URL,
            json={"model": config.OLLAMA_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=60,
        )
        log.info("[lifespan] Микро-LLM прогрета")
    except Exception as exc:
        log.warning(f"[lifespan] Прогрев не удался: {exc}")

    yield

    log.info("[lifespan] Остановка сервера...")
    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        log.info("[lifespan] Задача сканирования отменена")
    state.model = None
    log.info("[lifespan] Сервер остановлен")


__all__ = ["lifespan"]
