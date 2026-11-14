"""RAG retrieval helpers."""
try:
    from app import rag as _legacy
except ImportError:  # pragma: no cover
    import rag as _legacy

_normalize_query_for_search = _legacy._normalize_query_for_search
_filter_hits_by_entity = _legacy._filter_hits_by_entity
_collect_all_entity_rows = _legacy._collect_all_entity_rows

__all__ = [
    "_normalize_query_for_search", "_filter_hits_by_entity", "_collect_all_entity_rows",
]
