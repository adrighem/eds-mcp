"""Document text extraction helpers for PDF, DOCX, XLSX, and text files."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

from . import ErrorCode, error_envelope, ok_envelope

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 5
MAX_CONTENT_CHARS = 30000
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
Parser = Callable[[str], str]


def parse_pdf(file_path: str) -> str:
    """Extract plain text from all pages of a PDF document."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        page_text = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(page_text).strip()
    except ImportError:
        return "Error: pypdf library not installed."
    except (OSError, ValueError) as e:
        return f"Error parsing PDF: {e}"


def parse_docx(file_path: str) -> str:
    """Extract plain text paragraphs from a DOCX document."""
    try:
        from docx import Document

        doc = Document(file_path)
        return "\n".join(para.text for para in doc.paragraphs).strip()
    except ImportError:
        return "Error: python-docx library not installed."
    except (OSError, ValueError) as e:
        return f"Error parsing DOCX: {e}"


def parse_xlsx(file_path: str) -> str:
    """Extract table rows from an XLSX workbook."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(file_path, data_only=True)
        lines: list[str] = []
        for sheet in wb.worksheets:
            lines.append(f"### Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                lines.append(" | ".join(str(cell) if cell is not None else "" for cell in row))
            lines.append("")
        return "\n".join(lines).strip()
    except ImportError:
        return "Error: openpyxl library not installed."
    except (OSError, ValueError) as e:
        return f"Error parsing XLSX: {e}"


def parse_text(file_path: str) -> str:
    """Read a plain text, markdown, csv, or json file using UTF-8 with replacement."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        return f"Error reading text file: {e}"


DOCUMENT_PARSERS: dict[str, Parser] = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".xlsx": parse_xlsx,
    **{ext: parse_text for ext in TEXT_EXTENSIONS},
}


def supported_document_formats() -> str:
    """Return supported extensions in a stable human-readable order."""
    return ", ".join(sorted(DOCUMENT_PARSERS))


def truncate_for_context(content: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
    """Keep parsed document content within a predictable context budget."""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n\n[... content truncated due to length ...]"


async def parse_document_logic(file_path: str) -> str:
    """Extract and truncate text from local documents returning structured envelopes."""
    path = Path(file_path).resolve()
    if not path.is_file():
        return error_envelope(
            ErrorCode.NOT_FOUND,
            f"File not found: {file_path}",
            hint="Provide an existing local file path.",
        )

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            f"File is too large ({size_mb:.1f} MB). Max size for parsing is {MAX_FILE_SIZE_MB} MB.",
        )

    ext = path.suffix.lower()
    parser = DOCUMENT_PARSERS.get(ext)
    if not parser:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported document format '{ext}'. Supported: {supported_document_formats()}",
        )

    try:
        content = await asyncio.to_thread(parser, str(path))
    except (OSError, RuntimeError, ValueError) as e:
        logger.exception("Failed parsing document %s", path.name)
        return error_envelope(ErrorCode.PARSE_ERROR, f"Failed parsing document: {e}")

    if content.startswith("Error:"):
        return error_envelope(ErrorCode.PARSE_ERROR, content)

    orig_len = len(content)
    truncated = orig_len > MAX_CONTENT_CHARS
    truncated_content = truncate_for_context(content, MAX_CONTENT_CHARS)
    return ok_envelope(
        {
            "file": os.path.basename(str(path)),
            "content": truncated_content,
            "truncated": truncated,
            "chars": orig_len,
        }
    )
