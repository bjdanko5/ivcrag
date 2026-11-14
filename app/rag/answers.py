"""Focused RAG answer formatting and generation API."""
from . import (
    _format_department_answer,
    _format_phone_answer_from_hit,
    _build_md_table,
    _rag_answer,
)

__all__ = [
    "_format_department_answer", "_format_phone_answer_from_hit",
    "_build_md_table", "_rag_answer",
]
