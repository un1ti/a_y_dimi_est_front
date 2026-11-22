"""PDF text and table extraction with page-linked fragments.

No OCR. PyMuPDF table recognition is best-effort; always retain the raw page text.
"""
from dataclasses import dataclass

import pymupdf
from app.services.rag_packed_tables import packed_table_fragments


class PDFParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedFragment:
    page: int
    position: int
    text: str


@dataclass(frozen=True)
class ParsedPDF:
    page_count: int
    fragments: list[ParsedFragment]
    text_status: str


def split_text(text: str, chunk_size: int = 1400, overlap: int = 180) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + chunk_size // 2, end), text.rfind(" ", start + chunk_size // 2, end))
            if boundary > start:
                end = boundary + 1
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def extract_table_fragments(page: pymupdf.Page) -> list[str]:
    """Keep row-to-column mapping explicit when PyMuPDF can detect a table."""
    result: list[str] = []
    try:
        finder = page.find_tables()
        tables = finder.tables
    except (AttributeError, ValueError, RuntimeError):
        return result
    words = page.get_text("words") if tables else []
    for table in tables:
        try:
            packed = packed_table_fragments(page, table, words)
            if packed:
                result.extend(packed)
                continue
            rows = table.extract()
        except (AttributeError, ValueError, RuntimeError):
            continue
        if len(rows) < 2 or max((len(row) for row in rows), default=0) < 2:
            continue
        header = " | ".join(str(cell or "").strip().replace("\n", " ") for cell in rows[0])
        # Repeat column titles on every short group of rows so evidence includes
        # both the table's numeric values and their context.
        for offset in range(1, len(rows), 3):
            parts = [f"EXTRACTED TABLE (page {page.number + 1})", f"Columns: {header}"]
            for row in rows[offset:offset + 3]:
                parts.append("Row: " + " | ".join(str(cell or "").strip().replace("\n", " ") for cell in row))
            text = "\n".join(parts)
            if len(text) > 3500:
                result.extend(split_text(text, 1200, 0))
            else:
                result.append(text)
    return result


def parse_pdf(pdf_bytes: bytes, max_pages: int = 120) -> ParsedPDF:
    if not pdf_bytes.lstrip().startswith(b"%PDF-"):
        raise PDFParseError("File does not have a PDF header")
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise PDFParseError("Password-protected PDF is not supported")
            pages = len(pdf)
            if pages == 0 or pages > max_pages:
                raise PDFParseError(f"PDF page count must be between 1 and {max_pages}")
            fragments: list[ParsedFragment] = []
            for page_number, page in enumerate(pdf, start=1):
                text = page.get_text("text", sort=True)
                chunks = split_text(text)
                chunks.extend(extract_table_fragments(page))
                for position, chunk in enumerate(chunks, start=1):
                    fragments.append(ParsedFragment(page=page_number, position=position, text=chunk))
    except PDFParseError:
        raise
    except Exception as exc:
        raise PDFParseError("Could not parse PDF (damaged or unsupported structure)") from exc
    return ParsedPDF(page_count=pages, fragments=fragments, text_status="ok" if fragments else "no_text")
