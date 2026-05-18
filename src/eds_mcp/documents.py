import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def parse_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except ImportError:
        return "Error: pypdf library not installed."
    except Exception as e:
        return f"Error parsing PDF: {e}"

def parse_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text.strip()
    except ImportError:
        return "Error: python-docx library not installed."
    except Exception as e:
        return f"Error parsing DOCX: {e}"

def parse_xlsx(file_path: str) -> str:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(file_path, data_only=True)
        text = ""
        for sheet in wb.worksheets:
            text += f"### Sheet: {sheet.title}\n"
            for row in sheet.iter_rows(values_only=True):
                text += " | ".join([str(cell) if cell is not None else "" for cell in row]) + "\n"
            text += "\n"
        return text.strip()
    except ImportError:
        return "Error: openpyxl library not installed."
    except Exception as e:
        return f"Error parsing XLSX: {e}"

def parse_text(file_path: str) -> str:
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        return f"Error reading text file: {e}"

async def parse_document_logic(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    
    # Check file size (limit parsing to 5MB to avoid context issues)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > 5:
        return f"Error: File is too large ({size_mb:.1f} MB). Max size for parsing is 5 MB."

    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        content = parse_pdf(file_path)
    elif ext == ".docx":
        content = parse_docx(file_path)
    elif ext == ".xlsx":
        content = parse_xlsx(file_path)
    elif ext in [".txt", ".md", ".csv", ".json"]:
        content = parse_text(file_path)
    else:
        return f"Error: Unsupported document format '{ext}'. Supported: .pdf, .docx, .xlsx, .txt, .md, .csv, .json"

    # Truncate content if it's still too large for LLM context
    MAX_CHARS = 30000
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS] + "\n\n[... content truncated due to length ...]"
    
    return content