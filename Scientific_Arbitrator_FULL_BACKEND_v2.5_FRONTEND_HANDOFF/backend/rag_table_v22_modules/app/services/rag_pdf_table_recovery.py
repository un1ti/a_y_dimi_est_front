"""Best-effort recovery of borderless, text-aligned tables from an existing RAG PDF.

This never fabricates values or cell associations: only a PyMuPDF aligned-cell
matrix that independently passes rag_table_extraction's strict recognition is
returned. Called on demand during extraction or read-only preview.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import SimpleNamespace

import pymupdf

from app.services.rag_table_extraction import extract_rag_table_records, _metric_spec


@dataclass(frozen=True)
class RecoveredTableFragment:
    page: int
    text: str


def _explicit_caption(page, table_bbox) -> str | None:
    """Only use a nearby Table-N caption with one clearly named evaluation metric."""
    try:
        y0 = float(table_bbox[1])
        area = pymupdf.Rect(0, max(0, y0 - 110), page.rect.width, max(0, y0 - 2))
        surrounding = page.get_text("text", clip=area, sort=True)
    except (TypeError, ValueError, RuntimeError):
        return None
    candidates = []
    for line in surrounding.splitlines():
        line = line.strip()
        if not re.match(r"^Table\s+\d+[.:\s-]", line, re.I):
            continue
        if _metric_spec(line)[0] is not None:
            candidates.append(line)
    return candidates[0] if len(candidates) == 1 else None


def _table_text(page_number: int, headers: list[str], rows: list[list[str]],
                caption: str | None = None) -> list[str]:
    cleaned_headers = [str(v or "").strip().replace("\n", " ") for v in headers]
    if any("|" in v for v in cleaned_headers):
        return []  # Delimiter collision, cannot prove column association.
    groups = []
    for offset in range(0, len(rows), 3):
        parts = [f"EXTRACTED TABLE (page {page_number})",
                 "Columns: " + " | ".join(cleaned_headers)]
        if caption:
            parts.append("Caption: " + caption)
        for row in rows[offset:offset + 3]:
            cleaned = [str(v or "").strip().replace("\n", " ") for v in row]
            if any("|" in v for v in cleaned) or len(cleaned) != len(cleaned_headers):
                continue
            parts.append("Row: " + " | ".join(cleaned))
        if len(parts) > 2:
            group = "\n".join(parts)
            if len(group) <= 3500:
                groups.append(group)
    return groups


def recover_text_aligned_tables(pdf_bytes: bytes, *, max_pages: int = 120,
                                limit: int = 200) -> list[RecoveredTableFragment]:
    """Return only candidate table fragments with >=1 explicit complete RAG result."""
    output: list[RecoveredTableFragment] = []
    if not pdf_bytes.startswith(b"%PDF-"):
        return output
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass or document.page_count > max_pages:
                return output
            for page in document:
                if len(output) >= limit:
                    break
                try:
                    detected = page.find_tables(strategy="text").tables
                except (AttributeError, ValueError, RuntimeError):
                    continue
                for table in detected:
                    try:
                        matrix = table.extract()
                    except (AttributeError, ValueError, RuntimeError):
                        continue
                    # No headers in the top 3 rows = no reliable mapping.
                    matrix = [row for row in matrix if row and any(str(c or "").strip() for c in row)]
                    if not (2 <= len(matrix) <= 150):
                        continue
                    header_idx = next((i for i, row in enumerate(matrix[:3])
                                       if any(str(c or "").strip().casefold() in (
                                           "system", "method", "model", "approach", "rag variant", "rag system",
                                           "configuration", "baseline", "retriever", "dataset", "benchmark", "data set", "corpus", "test set")
                                              for c in row)), None)
                    if header_idx is None:
                        continue
                    header = matrix[header_idx]
                    rows = matrix[header_idx + 1:]
                    if len(header) < 2 or not rows:
                        continue
                    caption = _explicit_caption(page, table.bbox)
                    for text in _table_text(page.number + 1, header, rows, caption):
                        candidate = SimpleNamespace(id="preview", text=text, page=page.number + 1)
                        if extract_rag_table_records([candidate]).records:
                            output.append(RecoveredTableFragment(page=page.number + 1, text=text))
                            if len(output) >= limit:
                                break
    except (RuntimeError, ValueError, TypeError, pymupdf.FileDataError):
        return []
    return output
