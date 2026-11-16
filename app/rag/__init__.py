"""RAG package exposing refactored modules."""
from app.rag.answers import (
    _build_md_table,
    _format_department_answer,
    _format_phone_answer_from_hit,
    _rag_answer,
)
from app.rag.retrieval import _collect_all_entity_rows, _filter_hits_by_entity, _normalize_query_for_search

__all__ = [
    "_normalize_query_for_search",
    "_filter_hits_by_entity",
    "_collect_all_entity_rows",
    "_format_department_answer",
    "_format_phone_answer_from_hit",
    "_build_md_table",
    "_rag_answer",
]
