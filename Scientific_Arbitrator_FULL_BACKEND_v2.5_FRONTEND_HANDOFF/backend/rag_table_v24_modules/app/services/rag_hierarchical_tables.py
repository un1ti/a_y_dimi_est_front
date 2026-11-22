"""Strict geometry-based extraction of RAG comparison tables with three header axes.

Maps an explicit generator-model band, dataset band, and EM/F1 band to method
rows by native PDF word coordinates. Never treats prose, figures, or detached
numerical annotations as a grid. Returns *synthetic, traceable* table fragments
for the existing grounded table parser. The fragments are a reconstructed view:
quote_matched for such fragments verifies internal reconstruction, NOT an exact
PDF text span or experimental correctness.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.services.rag_table_extraction import _dataset_from_heading, _metric_spec, _NUM


@dataclass(frozen=True)
class HierarchicalFragment:
    page: int
    text: str


@dataclass(frozen=True)
class WordCell:
    x0: float
    x1: float
    text: str

    @property
    def mid(self) -> float:
        return (self.x0 + self.x1) / 2


def _lines(page: Any) -> list[tuple[float, list[WordCell]]]:
    words = page.get_text('words', sort=True)
    if len(words) > 20000:
        return []
    result: list[tuple[float, list[WordCell]]] = []
    for row in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        x0, y0, x1, y1, raw = row[:5]
        if not isinstance(raw, str) or not raw.strip():
            continue
        y = (y0 + y1) / 2
        item = WordCell(float(x0), float(x1), raw.strip())
        if result and abs(result[-1][0] - y) <= 2.6:
            result[-1][1].append(item)
        else:
            result.append((y, [item]))
    return [(y, sorted(cells, key=lambda c: c.x0)) for y, cells in result]


def _phrases(words: list[WordCell], *, gap: float = 12.0) -> list[WordCell]:
    """Join only neighbouring words that clearly form one visual heading."""
    out: list[WordCell] = []
    for w in words:
        if out and w.x0 - out[-1].x1 <= gap:
            prev = out[-1]
            out[-1] = WordCell(prev.x0, max(prev.x1, w.x1), prev.text + ' ' + w.text)
        else:
            out.append(w)
    return out


def _dataset_labels(cells: list[WordCell], n_pairs: int,
                    metric_columns: list[WordCell]) -> list[str] | None:
    dataset_cells = [c for c in cells if _dataset_from_heading(c.text)]
    if len(dataset_cells) != n_pairs:
        return None
    found = []
    for i, c in enumerate(dataset_cells):
        pair_center = (metric_columns[2*i].mid + metric_columns[2*i + 1].mid) / 2
        if abs(c.mid - pair_center) > 11.0:
            return None
        found.append(_dataset_from_heading(c.text))
    return found


def _model_names(model_words: list[WordCell], dataset_cells: list[WordCell],
                 datasets: list[str]) -> list[str] | None:
    """A repeated benchmark cycle must match an unambiguous model group band."""
    candidates = _phrases(model_words, gap=12.0)
    candidates = [c for c in candidates if c.text and not _NUM.fullmatch(c.text)
                  and _metric_spec(c.text)[0] is None]
    if not (2 <= len(candidates) <= 8):
        return None
    # A model band must cover multiple dataset columns; do not infer from a lone label.
    assigned = [min(range(len(candidates)), key=lambda i: abs(candidates[i].mid - cell.mid))
                for cell in dataset_cells]
    if len(set(assigned)) != len(candidates) or assigned != sorted(assigned):
        return None
    groups: list[list[int]] = [[] for _ in candidates]
    for i, j in enumerate(assigned):
        if abs(candidates[j].mid - dataset_cells[i].mid) > 65:
            return None
        groups[j].append(i)
    if any(len(g) < 2 for g in groups):
        return None
    template = [datasets[i] for i in groups[0]]
    if len(set(template)) != len(template):
        return None
    if any([datasets[i] for i in g] != template for g in groups[1:]):
        return None
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+\- ]{1,70}', c.text)
           for c in candidates):
        return None
    return [candidates[j].text for j in assigned]


def _table_on_page(page, *, max_rows: int = 80) -> list[HierarchicalFragment]:
    lines = _lines(page)
    page_n = page.number + 1
    fragments: list[HierarchicalFragment] = []
    for mi, (y_metric, metric_cols) in enumerate(lines):
        if not (8 <= len(metric_cols) <= 48 and len(metric_cols) % 2 == 0):
            continue
        metrics = [_metric_spec(c.text)[0] for c in metric_cols]
        if any(m not in ('Exact Match', 'F1') for m in metrics):
            continue
        # Alternating EM/F1 is a *verified* metric dimension, not guessed from values.
        if any(metrics[i:i+2] != ['Exact Match', 'F1'] for i in range(0, len(metrics), 2)):
            continue
        if any(metric_cols[i + 1].mid - metric_cols[i].mid < 12 for i in range(len(metric_cols)-1)):
            continue
        before = [(y, line) for y, line in lines[:mi] if 6 <= y_metric - y <= 35]
        pairs = len(metric_cols) // 2
        heading = []
        for y, line in before:
            labels = _dataset_labels(line, pairs, metric_cols)
            if labels is not None:
                heading.append((y, line, labels))
        if len(heading) != 1:
            continue
        y_datasets, dataset_cells, datasets = heading[0]
        # Dataset line must lie above metric line and below model heading.
        if not 8 <= y_metric - y_datasets <= 21:
            continue
        model_lines = [(y, line) for y, line in lines[:mi]
                       if 8 <= y_datasets - y <= 24 and any(w.x0 > metric_cols[0].x0 - 18 for w in line)]
        models = []
        for _, line in model_lines:
            possible = _model_names([w for w in line if w.x0 > metric_cols[0].x0 - 18],
                                    dataset_cells, datasets)
            if possible:
                models.append(possible)
        if len(models) != 1:
            continue
        model_by_pair = models[0]
        if not any(any(c.text.casefold() in ('methods','method','system','systems','models')
                       for c in line if c.mid < metric_cols[0].mid - 20)
                   for y, line in lines[:mi] if 6 <= y_metric - y <= 32):
            continue
        # Explicit source-backed dimension for *each* numeric cell.
        headers = ['Methods'] + [
            f'{datasets[j // 2]} ({metric_cols[j].text}) [generator={model_by_pair[j // 2]}]'
            for j in range(len(metric_cols))
        ]
        row_count = 0
        for y, cells in lines[mi+1:]:
            if y - y_metric > 400:
                break
            if any(c.text.casefold() == 'table' for c in cells) and row_count > 0:
                break
            numeric_cells = [c for c in cells if _NUM.fullmatch(c.text)]
            if len(numeric_cells) != len(metric_cols):
                continue
            if any(abs(value.mid - col.mid) > 4.0
                   for col, value in zip(metric_cols, numeric_cells)):
                continue
            label_cells = [c for c in cells if c.x1 < metric_cols[0].x0 - 1]
            if not label_cells or len(label_cells) > 4:
                continue
            label = ' '.join(c.text for c in label_cells)
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 +.*_\-]{1,70}', label):
                continue
            values = []
            for cell in numeric_cells:
                val = float(_NUM.fullmatch(cell.text).group(1).replace(',', '.'))
                if not 0 <= val <= 1:  # EM and F1 are fractions here, never arbitrary page numbers.
                    break
                values.append(cell.text)
            if len(values) != len(metric_cols):
                continue
            text = (f'EXTRACTED TABLE (page {page_n})\n'
                    + 'Columns: ' + ' | '.join(headers) + '\n'
                    + 'Row: ' + ' | '.join([label, *values]) + '\n'
                    + 'Source layout: native PDF aligned multi-level headers (not original reading order)')
            if len(text) > 3500:
                continue
            fragments.append(HierarchicalFragment(page_n, text))
            row_count += 1
            if row_count >= max_rows:
                break
    return fragments


def recover_hierarchical_tables(pdf_bytes: bytes, *, max_pages: int = 120,
                                limit: int = 200) -> list[HierarchicalFragment]:
    if not pdf_bytes.startswith(b'%PDF-'):
        return []
    try:
        import pymupdf
        with pymupdf.open(stream=pdf_bytes, filetype='pdf') as doc:
            if doc.needs_pass or doc.page_count > max_pages:
                return []
            result: list[HierarchicalFragment] = []
            for page in doc:
                result.extend(_table_on_page(page))
                if len(result) >= limit:
                    return result[:limit]
            return result
    except (RuntimeError, TypeError, ValueError, pymupdf.FileDataError):
        return []
