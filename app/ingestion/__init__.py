"""Ingestion package exposing the refactored modules."""
from .extractors import (
    _extract_docx,
    _extract_pdf,
    _extract_xlsx,
    _extract_docx_table_rows,
    _extract_pdf_table_rows,
    _extract_xlsx_table_rows,
    extract_text,
)
from .indexing import (
    chunk_text,
    delete_file_from_index,
    get_file_hash,
    index_file,
    _load_hashes,
    _save_hashes,
)
from .scanner import periodic_scan, scan_docs_dir

__all__ = [
    "_extract_docx",
    "_extract_pdf",
    "_extract_xlsx",
    "_extract_docx_table_rows",
    "_extract_pdf_table_rows",
    "_extract_xlsx_table_rows",
    "extract_text",
    "chunk_text",
    "get_file_hash",
    "delete_file_from_index",
    "index_file",
    "_load_hashes",
    "_save_hashes",
    "scan_docs_dir",
    "periodic_scan",
]
