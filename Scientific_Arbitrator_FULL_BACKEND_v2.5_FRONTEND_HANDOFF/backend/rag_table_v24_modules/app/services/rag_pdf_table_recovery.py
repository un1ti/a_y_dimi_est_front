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

from app.services.rag_hierarchical_tables import recover_hierarchical_tables, _table_on_page

from app.services.rag_table_extraction import (
    extract_rag_table_records, _metric_spec, _header_kind, _dataset_from_heading, _NUM
)


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



def _header_and_rows(matrix: list[list[str]]) -> tuple[list[str], list[list[str]]] | None:
    """Accept simple or provably aligned two-tier metric headings.

    For example: System / HotpotQA / (blank) / 2Wiki / (blank)
                 (blank) / EM / F1 / EM / F1.
    Do not propagate ambiguous dataset names or metrics.
    """
    if not (2 <= len(matrix) <= 150):
        return None
    for idx in range(min(5, len(matrix) - 1)):
        header = [str(c or "").strip().replace("\n", " ") for c in matrix[idx]]
        if not (2 <= len(header) <= 60) or not any(_header_kind(h) in {"system", "dataset"} for h in header):
            continue
        if any(_metric_spec(h)[0] for h in header[1:]):
            return header, matrix[idx + 1:]
        # A metric-free table can still be fully supported by a nearby,
        # unique source caption. The downstream extractor will reject it
        # without the explicit caption. Never infer EM from numbers alone.
        if (all(_dataset_from_heading(h) for h in header[1:])
                and len(matrix[idx + 1]) == len(header)
                and all(_NUM.fullmatch(str(v or "").strip()) for v in matrix[idx + 1][1:])):
            return header, matrix[idx + 1:]
        # Two-tier headings are valid only when each metric subcolumn has
        # both an explicit dataset and a separately named metric.
        if idx + 2 >= len(matrix):
            continue
        sub = [str(c or "").strip().replace("\n", " ") for c in matrix[idx + 1]]
        if len(sub) != len(header):
            continue
        if len([i for i, h in enumerate(sub) if _metric_spec(h)[0] is not None]) < 2:
            continue
        compound: list[str] = []
        dataset: str | None = None
        valid = True
        for col, (top, lower) in enumerate(zip(header, sub)):
            if col == 0 and _header_kind(top) in ("system", "dataset"):
                if lower and _metric_spec(lower)[0] is None:
                    valid = False
                    break
                compound.append(top)
                continue
            if top and _metric_spec(top)[0] is None:
                # Dataset label can group multiple subcolumns.
                dataset = _dataset_from_heading(top) if _header_kind(top) is None else None
            metric, _ = _metric_spec(lower)
            if metric is None or not dataset:
                valid = False
                break
            compound.append(f"{dataset} ({lower})")
        if valid:
            return compound, matrix[idx + 2:]
    return None


def _word_aligned_candidates(page, page_number: int) -> list[str]:
    """Strict position-based fallback if PyMuPDF table discovery misses a grid.

    Require explicit metric-bearing dataset headers, at least two aligned
    measurement rows, and numeric cells with matching x columns. No prose or
    free-floating numbers are interpreted as table rows.
    """
    words = page.get_text("words", sort=True)
    if len(words) > 20000:
        return []
    lines: list[list[tuple[float, float, float, float, str]]] = []
    for x0, y0, x1, y1, value, *_ in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        if not value.strip():
            continue
        cy = (y0 + y1) / 2
        if lines and abs(((lines[-1][0][1] + lines[-1][0][3]) / 2) - cy) < 2.5:
            lines[-1].append((float(x0), float(y0), float(x1), float(y1), str(value)))
        else:
            lines.append([(float(x0), float(y0), float(x1), float(y1), str(value))])

    normalized_lines: list[tuple[float, list[tuple[float, str]]]] = []
    for line in lines:
        line.sort(key=lambda w: w[0])
        y_center = (line[0][1] + line[0][3]) / 2
        cells: list[list] = []
        for x0, _, x1, _, word in line:
            if cells and x0 - cells[-1][2] <= 13:
                cells[-1][1] += " " + word
                cells[-1][2] = max(cells[-1][2], x1)
            else:
                cells.append([x0, word, x1])
        normalized_lines.append((y_center, [(x, txt.strip()) for x, txt, _ in cells]))

    output: list[str] = []
    for ix, (hy, cells) in enumerate(normalized_lines):
        if not (3 <= len(cells) <= 12) or _header_kind(cells[0][1]) != "system":
            continue
        cols = [(x, s) for x, s in cells]
        if any(_metric_spec(s)[0] is None or _dataset_from_heading(s) is None for _, s in cols[1:]):
            continue
        if any(cols[j + 1][0] - cols[j][0] < 30 for j in range(len(cols) - 1)):
            continue
        rows: list[list[str]] = []
        last_y = hy
        for ry, rcells in normalized_lines[ix + 1:ix + 26]:
            if ry - last_y > 42:
                break
            if len(rcells) != len(cols):
                if rows:
                    break
                continue
            align = all(abs(rx - hx) <= min(28, (cols[min(ci + 1, len(cols) - 1)][0] - hx) * .40 if ci < len(cols)-1 else 28)
                        for ci, ((rx, _), (hx, _)) in enumerate(zip(rcells, cols)))
            numeric = all(_NUM.fullmatch(s) for _, s in rcells[1:])
            system = rcells[0][1]
            if not (align and numeric and system and _NUM.fullmatch(system) is None):
                if rows:
                    break
                continue
            rows.append([s for _, s in rcells])
            last_y = ry
            if len(rows) >= 30:
                break
        if len(rows) >= 2:
            # Each value remains in its own exact physical x-column.
            candidate_fragments = _table_text(page_number, [s for _, s in cols], rows)
            for fragment in candidate_fragments:
                example = SimpleNamespace(id="preflight", page=page_number, text=fragment)
                if extract_rag_table_records([example]).records:
                    output.append(fragment)
            if output:
                break
    return output


def describe_pdf_tables(pdf_bytes: bytes, *, max_pages: int = 120) -> dict:
    """Non-mutating pipeline diagnostics. No raw page text is returned."""
    if not pdf_bytes.startswith(b"%PDF-"):
        return {"pdf_readable": False, "reason": "invalid_pdf_header", "pages": []}
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                return {"pdf_readable": False, "reason": "encrypted", "pages": []}
            if len(doc) > max_pages:
                return {"pdf_readable": False, "reason": "page_limit_exceeded", "pages": []}
            details = []
            for page in doc:
                counts = {}
                for strategy in ("lines", "text"):
                    try:
                        counts[strategy] = len(page.find_tables(strategy=strategy).tables)
                    except (RuntimeError, AttributeError, ValueError):
                        counts[strategy] = None
                details.append({
                    "page": page.number + 1,
                    "text_chars": len(page.get_text("text")),
                    "words": len(page.get_text("words")),
                    "images": len(page.get_images(full=True)),
                    "line_tables": counts["lines"],
                    "text_tables": counts["text"],
                    "aligned_fragments": len(_word_aligned_candidates(page, page.number + 1)),
                    "hierarchical_fragments": len(_table_on_page(page)),
                })
            return {"pdf_readable": True, "page_count": len(doc), "pages": details}
    except (ValueError, TypeError, RuntimeError, pymupdf.FileDataError) as exc:
        return {"pdf_readable": False, "reason": type(exc).__name__, "pages": []}

def recover_text_aligned_tables(pdf_bytes: bytes, *, max_pages: int = 120,
                                limit: int = 300) -> list[RecoveredTableFragment]:
    """Strict PDF table candidates from native table or geometric text alignment."""
    output: list[RecoveredTableFragment] = []
    if not pdf_bytes.startswith(b"%PDF-"):
        return output
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass or document.page_count > max_pages:
                return output
            hierarchical = recover_hierarchical_tables(pdf_bytes, max_pages=max_pages, limit=limit)
            strong_pages = {f.page for f in hierarchical}
            output.extend(RecoveredTableFragment(page=f.page, text=f.text) for f in hierarchical)
            for page in document:
                if len(output) >= limit:
                    break
                # A complete 3-axis reconstruction supersedes malformed flattened grids.
                if page.number + 1 in strong_pages:
                    continue
                page_fragments: list[str] = []
                try:
                    tables = page.find_tables(strategy="text").tables
                except (AttributeError, ValueError, RuntimeError):
                    tables = []
                for table in tables:
                    try:
                        matrix = table.extract()
                    except (AttributeError, ValueError, RuntimeError):
                        continue
                    matrix = [row for row in matrix if row and any(str(c or "").strip() for c in row)]
                    found = _header_and_rows(matrix)
                    if found is None:
                        continue
                    headers, rows = found
                    caption = _explicit_caption(page, table.bbox)
                    for fragment in _table_text(page.number + 1, headers, rows, caption):
                        example = SimpleNamespace(id="preflight", text=fragment, page=page.number + 1)
                        if extract_rag_table_records([example]).records:
                            page_fragments.append(fragment)
                # Choose the stronger geometry-backed reconstruction for this
                # page. Never union partly overlapping tables and create dupes.
                aligned = _word_aligned_candidates(page, page.number + 1)
                native_count = sum(len(extract_rag_table_records([
                    SimpleNamespace(id="candidate", text=t, page=page.number + 1)
                ]).records) for t in page_fragments)
                aligned_count = sum(len(extract_rag_table_records([
                    SimpleNamespace(id="candidate", text=t, page=page.number + 1)
                ]).records) for t in aligned)
                if aligned_count > native_count:
                    page_fragments = aligned
                for text in page_fragments:
                    output.append(RecoveredTableFragment(page=page.number + 1, text=text))
                    if len(output) >= limit:
                        break
    except (RuntimeError, ValueError, TypeError, pymupdf.FileDataError):
        return []
    return output
