"""RAG direct-answer formatters and answer pipeline entry points."""
from . import _legacy

_format_department_answer = _legacy._format_department_answer
_format_phone_answer_from_hit = _legacy._format_phone_answer_from_hit
_build_md_table = _legacy._build_md_table
_rag_answer = _legacy._rag_answer

__all__ = [
    "_format_department_answer", "_format_phone_answer_from_hit",
    "_build_md_table", "_rag_answer",
]
