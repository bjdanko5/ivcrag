"""Document extraction entry points."""
from . import _legacy

_extract_docx = _legacy._extract_docx
_extract_pdf = _legacy._extract_pdf
_extract_xlsx = _legacy._extract_xlsx
_extract_docx_table_rows = _legacy._extract_docx_table_rows
_extract_pdf_table_rows = _legacy._extract_pdf_table_rows
_extract_xlsx_table_rows = _legacy._extract_xlsx_table_rows
extract_text = _legacy.extract_text

__all__ = [
    "_extract_docx", "_extract_pdf", "_extract_xlsx",
    "_extract_docx_table_rows", "_extract_pdf_table_rows",
    "_extract_xlsx_table_rows", "extract_text",
]
