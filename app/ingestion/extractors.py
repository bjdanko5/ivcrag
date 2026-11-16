"""Extraction helpers for all supported document formats."""
import re
from pathlib import Path
from typing import List

from app.state import state


def _extract_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts: List[str] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] DOCX {path.name}: {len(text)} символов")
    return text


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: List[str] = []
    for index, page in enumerate(reader.pages):
        extracted = page.extract_text() or ""
        if extracted.strip():
            parts.append(f"=== Page {index + 1} ===\n{extracted}")
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] PDF {path.name}: {len(text)} символов, страниц: {len(reader.pages)}")
    return text


def _extract_xlsx(path: Path) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(str(path), data_only=True)
    parts: List[str] = []
    for sheet in workbook.worksheets:
        parts.append(f"=== Лист: {sheet.title} ===")
        for row in sheet.iter_rows(values_only=True):
            values = [str(value) if value is not None else "" for value in row]
            if any(values):
                parts.append(" | ".join(values))
    text = "\n".join(parts)
    state.log.debug(f"[extract_text] XLSX {path.name}: {len(text)} символов")
    return text


def _extract_docx_table_rows(path: Path) -> List[str]:
    import docx

    doc = docx.Document(str(path))
    enriched_rows: List[str] = []
    for table in doc.tables:
        if not table.rows:
            continue
        headers = [cell.text.strip().replace("\n", " ") for cell in table.rows[0].cells]
        for row in table.rows[1:]:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if not any(cells):
                continue
            if len(headers) == len(cells):
                record = [f"{header}: {value}" for header, value in zip(headers, cells) if value]
                chunk = f"[{path.name}] " + " | ".join(record)
            else:
                chunk = f"[{path.name}] " + " | ".join(cells)
            enriched_rows.append(chunk)
    return enriched_rows


def _extract_pdf_table_rows(path: Path) -> List[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"
    full_text = re.sub(r"<[^>]+>", " ", full_text)
    full_text = re.sub(r"\s+", " ", full_text)

    pattern = re.compile(
        r"(\d{1,2})\s*([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*(\d{3})\s*100\s*(\d{3})\s*(8\(\d{3,4}\)[\d\-]+)"
    )
    enriched_rows: List[str] = []
    for number, fio, internal, area, city in pattern.findall(full_text):
        chunk = (
            f"[{path.name}] №: {number} | Ф.И.О.: {fio} | "
            f"Внутренний: {internal} | Городской: {city}"
        )
        enriched_rows.append(chunk)
    return enriched_rows


def _extract_xlsx_table_rows(path: Path) -> List[str]:
    import openpyxl

    workbook = openpyxl.load_workbook(str(path), data_only=True)
    enriched_rows: List[str] = []

    for sheet in workbook.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        headers = None
        last_dept = ""
        last_dept_phone = ""

        for row in rows_iter:
            values = [str(value).strip().replace("\n", " ") if value is not None else "" for value in row]
            if not any(values):
                continue
            if headers is None:
                headers = values
                continue

            for index, header in enumerate(headers):
                header_norm = header.lower().replace("ё", "е")
                if header_norm in {"отдел", "отдел в тел."}:
                    if index < len(values):
                        if values[index]:
                            if header_norm == "отдел":
                                last_dept = values[index]
                            else:
                                last_dept_phone = values[index]
                        else:
                            values[index] = last_dept if header_norm == "отдел" else last_dept_phone

            parts: List[str] = []
            fio_multi: List[str] = []
            for key, value in zip(headers, values):
                if not value:
                    continue
                key_norm = key.lower().replace("ё", "е")
                if key_norm in {"ф.и.о.", "фио", "фамилия"}:
                    found = re.findall(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}", value)
                    found = [item for item in found if len(item.split()) >= 2]
                    if len(found) > 1:
                        fio_multi = found
                        continue
                parts.append(f"{key}: {value}")

            if fio_multi:
                for one_fio in fio_multi:
                    person_parts = [f"Ф.И.О.: {one_fio}"] + parts
                    enriched_rows.append(f"[{path.name}] " + " | ".join(person_parts))
            elif parts:
                enriched_rows.append(f"[{path.name}] " + " | ".join(parts))

    state.log.debug(f"[_extract_xlsx_table_rows] {path.name}: {len(enriched_rows)} строк")
    return enriched_rows


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    state.log.debug(f"[extract_text] Файл: {path.name}, расширение: {ext}")

    if ext in {
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".py",
        ".sh",
        ".bash",
        ".php",
        ".js",
        ".ts",
        ".json",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".sql",
    }:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
            state.log.debug(f"[extract_text] Прочитано {len(text)} символов из {path.name}")
            return text
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[extract_text] Ошибка чтения {path.name}: {exc}")
            return ""

    if ext == ".docx":
        try:
            enriched = _extract_docx_table_rows(path)
            if enriched:
                return "\n---\n".join(enriched)
            return _extract_docx(path)
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[extract_text] Ошибка DOCX {path.name}: {exc}")
            return ""

    if ext == ".pdf":
        try:
            enriched = _extract_pdf_table_rows(path)
            if enriched:
                state.log.debug(f"[extract_text] PDF {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            return _extract_pdf(path)
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[extract_text] Ошибка PDF {path.name}: {exc}")
            return ""

    if ext in {".xlsx", ".xls"}:
        try:
            enriched = _extract_xlsx_table_rows(path)
            if enriched:
                state.log.debug(f"[extract_text] XLSX {path.name} распознан как таблица, найдено {len(enriched)} строк")
                return "\n---\n".join(enriched)
            return _extract_xlsx(path)
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[extract_text] Ошибка XLSX {path.name}: {exc}")
            return ""

    if ext == ".doc":
        state.log.warning(f"[extract_text] .doc не поддержан: {path.name}")
        return ""

    state.log.warning(f"[extract_text] Неизвестное расширение: {ext} ({path.name})")
    return ""


__all__ = [
    "_extract_docx",
    "_extract_pdf",
    "_extract_xlsx",
    "_extract_docx_table_rows",
    "_extract_pdf_table_rows",
    "_extract_xlsx_table_rows",
    "extract_text",
]
