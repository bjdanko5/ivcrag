"""Native service endpoints and Redis-backed task processing."""
import os
import traceback

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException
from qdrant_client import models

try:
    import app.config as config
    import app.state as state
    from app.ingestion.scanner import scan_docs_dir
    from app.schemas import EmbedRequest, EmbedResponse
except ImportError:  # pragma: no cover
    import config
    import state
    from ingestion.scanner import scan_docs_dir
    from schemas import EmbedRequest, EmbedResponse

router = APIRouter()


def background_rag_pipeline(task_id: str):
    try:
        question = state.r_client.get(f"task:text:{task_id}")
        if not question:
            state.log.error(f"[{task_id}] Вопрос не найден в Redis")
            state.r_client.set(f"task:status:{task_id}", "error", ex=config.REDIS_TTL)
            return

        state.r_client.set(f"task:status:{task_id}", "searching", ex=config.REDIS_TTL)
        state.log.info(f"[{task_id}] Поиск контекста для: {question}")
        query_vector = list(state._dense_model.query_embed(f"query: {question}"))[0].tolist()

        query_filter = None
        file_match = __import__("re").search(
            r'[\w.-]+\.(?:md|txt|pdf|docx|xlsx|xls|py|sh|json|ya?ml)',
            question,
            __import__("re").IGNORECASE,
        )
        if file_match:
            detected_source = file_match.group(0)
            state.log.info(f"[{task_id}] Фильтр по источнику: {detected_source}")
            query_filter = models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value=detected_source))]
            )

        hits = state.qdrant_client.query_points(
            collection_name=config.COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=config.TOP_K,
            with_payload=True,
        ).points
        if not hits:
            state.r_client.set(f"task:status:{task_id}", "ok", ex=config.REDIS_TTL)
            state.r_client.set(
                f"task:answer:{task_id}",
                "В базе данных не найдено релевантных фрагментов.",
                ex=config.REDIS_TTL,
            )
            return

        context_parts, total = [], 0
        for hit in hits:
            src = hit.payload.get("source", "?")
            idx = hit.payload.get("chunk_index", "?")
            text = hit.payload.get("text", "")
            block = f"[{src} | chunk {idx}]\n{text}\n"
            if total + len(block) > config.MAX_CONTEXT_CHARS:
                break
            context_parts.append(block)
            total += len(block)

        context = "\n---\n".join(context_parts)
        state.log.info(f"[{task_id}] Контекст: {len(context_parts)} чанков, {total} символов")

        sources = list({h.payload.get("source", "?") for h in hits})
        state.r_client.set(f"task:sources:{task_id}", ", ".join(sources), ex=config.REDIS_TTL)
        state.r_client.set(f"task:status:{task_id}", "generating", ex=config.REDIS_TTL)
        state.log.info(f"[{task_id}] Отправка в llama-server...")
        user_prompt = config.USER_PROMPT_TEMPLATE.format(context=context, question=question)

        resp = requests.post(
            config.LLAMA_SERVER_URL,
            json={
                "model": config.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": config.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": config.MAX_ANSWER_TOKENS,
                "temperature": 0.3,
                "top_p": 0.9,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"
        state.r_client.set(f"task:answer:{task_id}", answer, ex=config.REDIS_TTL)
        state.r_client.set(f"task:status:{task_id}", "ok", ex=config.REDIS_TTL)
        state.log.info(f"[{task_id}] Задача выполнена")
    except Exception as exc:  # pragma: no cover
        state.log.error(f"Ошибка пайплайна {task_id}: {exc}")
        state.log.error(traceback.format_exc())
        state.r_client.set(f"task:status:{task_id}", "error", ex=config.REDIS_TTL)


@router.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    if not state.model:
        raise HTTPException(status_code=503, detail="Model not loaded")
    embeddings = [list(state._dense_model.embed([f"passage: {t}"]))[0].tolist() for t in request.texts]
    return EmbedResponse(embeddings=embeddings)


@router.post("/send/{task_id}")
async def send_task(task_id: str, background_tasks: BackgroundTasks):
    if not state.r_client.exists(f"task:text:{task_id}"):
        raise HTTPException(status_code=404, detail="Task text not found in Redis.")
    background_tasks.add_task(background_rag_pipeline, task_id)
    return {"status": "accepted", "task_id": task_id}


@router.get("/status/{task_id}")
async def get_status(task_id: str):
    status = state.r_client.get(f"task:status:{task_id}")
    if not status:
        return {"status": "not_found"}
    return {"status": status}


@router.get("/health")
async def health():
    redis_ok = False
    try:
        redis_ok = bool(state.r_client and state.r_client.ping())
    except Exception:
        redis_ok = False
    return {
        "status": "ok",
        "model_loaded": state._dense_model is not None,
        "qdrant_connected": state.qdrant_client is not None,
        "redis_connected": redis_ok,
        "docs_dir": str(config.DOCS_DIR),
        "docs_dir_exists": config.DOCS_DIR.exists(),
        "tracked_files": len(state.file_hashes),
    }


@router.post("/scan")
async def trigger_scan():
    state.log.info("[API /scan] Ручной триггер скана")
    summary = scan_docs_dir()
    return {"status": "ok", "summary": summary}


@router.get("/debug/state")
async def debug_state():
    files_in_dir = []
    if config.DOCS_DIR.exists():
        for root, dirs, files in os.walk(config.DOCS_DIR):
            dirs[:] = [d for d in dirs if d not in config.IGNORE_DIRS]
            for file_name in files:
                path = config.Path(root) / file_name
                files_in_dir.append({
                    "path": str(path),
                    "ext": path.suffix.lower(),
                    "allowed": path.suffix.lower() in config.ALLOWED_EXTENSIONS,
                    "size": path.stat().st_size if path.exists() else -1,
                })
    return {
        "docs_dir": str(config.DOCS_DIR),
        "docs_dir_exists": config.DOCS_DIR.exists(),
        "allowed_extensions": sorted(config.ALLOWED_EXTENSIONS),
        "tracked_files_in_memory": {str(k): v[:12] for k, v in state.file_hashes.items()},
        "files_on_disk": files_in_dir,
        "collection": config.COLLECTION_NAME,
        "model_dim": state.model.get_embedding_dimension() if state.model else None,
    }


__all__ = ["router", "background_rag_pipeline"]
