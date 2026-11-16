"""RAG retrieval helpers and entity matching."""
import re
from typing import List

from app.state import config, state


def _normalize_query_for_search(question: str) -> str:
    words = question.split()
    result = []
    for word in words:
        if word and word[0].isupper() and len(word) > 4:
            if word.endswith(("ко", "КО", "Ко")) and len(word) > 5:
                word = word[:-1]
            elif word.endswith(("а", "я", "у", "ю", "ой", "ей", "ым", "им", "ом", "ем")):
                word = word[:-1]
        result.append(word)
    return " ".join(result)


def _filter_hits_by_entity(hits, question: str):
    entity_words = [
        config._normalize_text(word)
        for word in re.findall(r"[А-ЯЁA-Z][а-яёa-z]{3,}", question)
        if config._normalize_text(word)
        not in {
            "что",
            "как",
            "где",
            "когда",
            "почему",
            "зачем",
            "какой",
            "какая",
            "какие",
            "телефон",
            "директора",
        }
    ]
    if not entity_words:
        return hits

    stems = []
    for word in entity_words:
        if word.endswith("ко") and len(word) > 5:
            stems.append(word[:-1])
        elif len(word) >= 5:
            stems.append(word[:5])
        elif len(word) >= 4:
            stems.append(word[:4])

    matched = [hit for hit in hits if any(stem in config._normalize_text(hit.payload.get("text", "")) for stem in stems)]
    return matched if matched else hits


def _collect_all_entity_rows(source_name: str, question: str, limit: int = 200) -> list:
    entities = re.findall(r"[А-ЯЁA-Z][а-яёa-z]{3,}", question or "")
    ignore = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая", "какие", "телефон", "директора", "комната", "отдел"}
    entities = [entity for entity in entities if config._normalize_text(entity) not in ignore]
    if not entities:
        return []

    def stems_for(entity: str):
        normalized = config._normalize_text(entity)
        output = []
        if normalized.endswith("ко") and len(normalized) > 5:
            output.append(normalized[:-1])
        if len(normalized) >= 5:
            output.append(normalized[:5])
        if len(normalized) >= 4:
            output.append(normalized[:4])
        return output

    all_stems = []
    for entity in entities:
        all_stems.extend(stems_for(entity))
    if not all_stems:
        return []

    try:
        scroll_filter = state.models.Filter(
            must=[state.models.FieldCondition(key="source", match=state.models.MatchValue(value=source_name))]
        )
        points, _ = state.qdrant_client.scroll(
            collection_name=config.COLLECTION_NAME,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as exc:  # pragma: no cover
        state.log.warning(f"[_collect_all_entity_rows] scroll failed: {exc}")
        return []

    rows = []
    for point in points:
        text = point.payload.get("text", "") if point.payload else ""
        normalized_text = config._normalize_text(text)
        if any(stem in normalized_text for stem in all_stems):
            rows.append(text)
    return rows


__all__ = [
    "_normalize_query_for_search",
    "_filter_hits_by_entity",
    "_collect_all_entity_rows",
]
