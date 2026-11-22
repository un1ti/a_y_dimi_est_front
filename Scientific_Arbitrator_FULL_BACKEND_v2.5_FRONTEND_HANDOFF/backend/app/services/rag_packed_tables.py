"""Recover ruled cells that contain several physical rows or metric columns."""
import re

from app.services.rag_table_extraction import _METRIC, _NUM, _header_kind


def _caption_dataset(page, bbox):
    left, top, right, _ = bbox
    captions = []
    for x0, _, x1, bottom, text, *_ in page.get_text("blocks"):
        if not 0 <= top - bottom <= 16 or not left <= (x0 + x1) / 2 <= right:
            continue
        line = " ".join(text.split())
        if re.match(r"^Table\s+\d+[.:]", line, re.I):
            captions.append(line)
    if len(captions) == 1:
        match = re.search(r"\bon ((?:QA )?dataset of the [\w -]+|[\w-]+)\.$", captions[0], re.I)
        if match:
            return match[1]
    return None


def _word_lines(words, cell):
    """Words with centres inside this PDF cell, grouped on the same baseline."""
    x0, y0, x1, y1 = cell
    selected = []
    for left, top, right, bottom, word, *_ in words:
        x, y = (left + right) / 2, (top + bottom) / 2
        if x0 <= x < x1 and y0 <= y < y1:
            selected.append((y, x, word))
    lines = []
    for y, x, word in sorted(selected):
        if not lines or y - lines[-1][0] > 2:
            lines.append((y, []))
        lines[-1][1].append((x, word))
    return [(y, sorted(items)) for y, items in lines]


def packed_table_fragments(page, table, words):
    rows = table.rows
    if len(rows) < 2 or len(rows[0].cells) < 2 or not all(rows[0].cells):
        return []
    first = [" ".join(w for _, line in _word_lines(words, cell) for _, w in line)
             for cell in rows[0].cells]
    if _header_kind(first[0]) != "system":
        return []
    # In a two-tier grid the left label spans both header rows.
    grouped = len(rows) >= 3 and rows[1].cells[0] is None
    header_index = 1 if grouped else 0
    labels = first[1:] if grouped else [_caption_dataset(page, table.bbox)] * (len(first) - 1)
    metric_cells = rows[header_index].cells[1:]
    if not all(labels) or not all(metric_cells) or len(metric_cells) != len(labels):
        return []
    bands = []
    for cell in metric_cells:
        lines = _word_lines(words, cell)
        if len(lines) != 1:
            return []
        headings = lines[0][1]
        if len(headings) < 2 or not all(_METRIC.fullmatch(h) for _, h in headings):
            return []
        bands.append(headings)
    fragments = []
    for row in rows[header_index + 1:]:
        if not all(row.cells) or len(row.cells) != len(bands) + 1:
            continue
        methods = _word_lines(words, row.cells[0])
        for dataset, headings, cell in zip(labels, bands, row.cells[1:]):
            values = _word_lines(words, cell)
            if len(methods) != len(values):
                continue
            for (my, label), (vy, numbers) in zip(methods, values):
                if abs(my - vy) > 2 or len(numbers) != len(headings):
                    continue
                # Each numeric centre must match its own metric, not the next one.
                if not all(_NUM.fullmatch(v) and min(range(len(headings)), key=lambda j: abs(x - headings[j][0])) == i
                           for i, (x, v) in enumerate(numbers)):
                    continue
                method = " ".join(w for _, w in label)
                if "|" in method or "|" in dataset or not re.search(r"[A-Za-z]", method):
                    continue
                header = " | ".join(h for _, h in headings)
                data = " | ".join(v for _, v in numbers)
                fragments.append(f"EXTRACTED TABLE (page {page.number + 1})\n"
                                 f"Columns: System | Dataset | {header}\n"
                                 f"Row: {method} | {dataset} | {data}")
    return fragments
