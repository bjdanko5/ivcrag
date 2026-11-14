"""Build indexing and scanning around the refactored extraction helpers."""
import hashlib
import json as _json
import os
import re
import traceback
from pathlib import Path
from typing import Dict, List

from app.state import config, state
from app.ingestion.extractors import extract_text


def chunk_text(text: str, max_chars: int, overlap: int) -> List[str]:
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    state.log.debug(f"[chunk_text] Получено {len(chunks)} чанков из {len(text)} символов")
    return chunks


def get_file_hash(path: Path) -> str:
    if config.SCAN_METHOD == "mtime":
        try:
            stat_result = path.stat()
            digest = f"{stat_result.st_mtime_ns}_{stat_result.st_size}"
            state.log.debug(f"[get_file_hash] {path.name} (mtime) -> {digest}")
            return digest
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[get_file_hash] stat {path.name}: {exc}")
            return ""

    hasher = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            hasher.update(handle.read())
        digest = hasher.hexdigest()
        state.log.debug(f"[get_file_hash] {path.name} (md5) -> {digest[:12]}…")
        return digest
    except Exception as exc:  # pragma: no cover
        state.log.error(f"[get_file_hash] md5 {path.name}: {exc}")
        return ""


def _load_hashes():
    if not config.SCAN_PERSIST:
        state.log.info("[hashes] persist=false — хеши не загружаются")
        return
    if not config.SCAN_HASHES_FILE.exists():
        state.log.info(f"[hashes] {config.SCAN_HASHES_FILE} не найден — будет первичная индексация")
        return
    try:
        raw = _json.loads(config.SCAN_HASHES_FILE.read_text(encoding="utf-8"))
        state.file_hashes = {Path(key): value for key, value in raw.items()}
        state.log.info(f"[hashes] Загружено {len(state.file_hashes)} хешей из {config.SCAN_HASHES_FILE}")
    except Exception as exc:  # pragma: no cover
        state.log.warning(f"[hashes] load failed: {exc}")


def _save_hashes():
    if not config.SCAN_PERSIST:
        return
    try:
        config.SCAN_HASHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        raw = {str(path): value for path, value in state.file_hashes.items()}
        config.SCAN_HASHES_FILE.write_text(_json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        state.log.warning(f"[hashes] save failed: {exc}")


def delete_file_from_index(source_name: str):
    state.log.info(f"[delete_file_from_index] Удаляю {source_name} из Qdrant...")
    try:
        state.qdrant_client.delete(
            collection_name=config.COLLECTION_NAME,
            points_selector=state.models.Filter(
                must=[
                    state.models.FieldCondition(
                        key="source",
                        match=state.models.MatchValue(value=source_name),
                    )
                ]
            ),
        )
        state.log.info(f"[delete_file_from_index] Успешно удалён {source_name}")
    except Exception as exc:  # pragma: no cover
        state.log.error(f"[delete_file_from_index] Ошибка удаления {source_name}: {exc}")


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
        raw_chunks = chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)

    if not raw_chunks:
        state.log.warning(f"[index_file] chunk_text вернул 0 чанков: {source_name}")
        return 0

    points = []
    total_batches = (len(raw_chunks) + config.BATCH_SIZE - 1) // config.BATCH_SIZE

    for batch_start in range(0, len(raw_chunks), config.BATCH_SIZE):
        batch_num = batch_start // config.BATCH_SIZE + 1
        batch_raw = raw_chunks[batch_start: batch_start + config.BATCH_SIZE]
        state.log.debug(
            f"[index_file] Батч {batch_num}/{total_batches} ({len(batch_raw)} текстов) для {source_name}"
        )

        try:
            dense_texts = [f"passage: {item}" for item in batch_raw]
            dense_vectors = [vector.tolist() for vector in state._dense_model.embed(dense_texts)]
            sparse_vectors = list(state._sparse_model.embed(batch_raw))
            state.log.debug(
                f"[index_file] Получено {len(dense_vectors)} dense и {len(sparse_vectors)} sparse векторов"
            )
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[index_file] Ошибка векторизации батча {batch_num} для {source_name}: {exc}")
            state.log.debug(traceback.format_exc())
            continue

        for offset, (dense_vec, sparse_emb) in enumerate(zip(dense_vectors, sparse_vectors)):
            chunk_index = batch_start + offset
            chunk_id = hashlib.md5(f"{source_name}_{chunk_index}".encode()).hexdigest()
            sparse_vec = state.models.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist(),
            )
            points.append(
                state.models.PointStruct(
                    id=chunk_id,
                    vector={"dense": dense_vec, "sparse": sparse_vec},
                    payload={
                        "source": source_name,
                        "chunk_index": chunk_index,
                        "text": batch_raw[offset],
                    },
                )
            )

    if points:
        state.log.debug(f"[index_file] Отправляю {len(points)} точек в Qdrant...")
        try:
            state.qdrant_client.upsert(collection_name=config.COLLECTION_NAME, points=points)
            state.log.info(f"[index_file] УСПЕХ: {len(points)} чанков для {source_name}")
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[index_file] Ошибка upsert в Qdrant для {source_name}: {exc}")
            return 0
    else:
        state.log.warning(f"[index_file] Нет точек для загрузки: {source_name}")
        return 0

    return len(points)


__all__ = [
    "chunk_text",
    "get_file_hash",
    "_load_hashes",
    "_save_hashes",
    "delete_file_from_index",
    "index_file",
]
