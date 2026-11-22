"""Conservative, deterministic extraction from structurally detected RAG PDF tables.

Only processes explicit EXTRACTED TABLE fragments made by pdf_parser.extract_table_fragments.
A cell value is associated with the header from the SAME table fragment and row index.
Plain PDF text is deliberately not interpreted as a grid. Nothing is inferred from
neighbouring paragraphs, dataset reputation, or numerical similarity alone.

This is source traceability, NOT independent scientific validation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.db.models import SourceFragment

_NUM = re.compile(r"^\s*([-+]?(?:\d+(?:[.,]\d*)?|\.\d+))\s*(%)?\s*$")
_SYSTEM_HEADERS = frozenset({"system", "method", "model", "approach", "rag variant", "rag system", "configuration", "baseline", "retriever"})
_DATASET_HEADERS = frozenset({"dataset", "benchmark", "data set", "corpus", "test set"})
_METRIC = re.compile(
    r"(?<![A-Za-z])(?P<name>Exact\s+Match|EM|F1|Recall|Precision|NDCG|MRR|Hit\s*Rate|Hit@\d+|Accuracy)"
    r"(?:\s*@\s*(?P<k>\d+))?(?![A-Za-z])", re.IGNORECASE,
)
_KNOWN_DATASETS = (
    "HotpotQA", "2WikiMultiHopQA", "2Wiki", "MuSiQue", "TriviaQA", "Natural Questions",
    "NQ", "WebQuestions", "WQ", "PopQA", "FEVER", "ASQA", "Bamboogle", "SQuAD", "WikiQA",
)
_MAX_TABLE_FRAGMENTS = 1200
_MAX_RECORDS = 200


@dataclass(frozen=True)
class TableExtraction:
    records: list[dict[str, Any]]
    table_fragment_count: int
    skipped_rows: int
    complete_context_count: int


def _header_kind(header: str) -> str | None:
    raw = re.sub(r"\s+", " ", header.strip().casefold())
    if raw in _SYSTEM_HEADERS:
        return "system"
    if raw in _DATASET_HEADERS:
        return "dataset"
    return None


def _metric_spec(label: str) -> tuple[str | None, int | None]:
    found = list(_METRIC.finditer(label))
    if len(found) != 1:
        return None, None
    hit = found[0]
    literal = re.sub(r"\s+", " ", hit.group("name")).strip().casefold()
    name = {
        "em": "Exact Match", "exact match": "Exact Match", "f1": "F1",
        "recall": "Recall", "precision": "Precision", "ndcg": "NDCG",
        "mrr": "MRR", "accuracy": "Accuracy", "hit rate": "Hit Rate",
    }.get(literal, "Hit Rate" if literal.startswith("hit@") else None)
    k = int(hit.group("k")) if hit.group("k") else None
    if literal.startswith("hit@"):
        k = int(literal.split("@")[1])
    return name, k


def _dataset_from_heading(heading: str) -> str | None:
    for name in _KNOWN_DATASETS:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", heading, re.I):
            return name
    # An arbitrary dataset name may be explicit in a header like "MyQA (Exact Match)".
    metric, _ = _metric_spec(heading)
    if metric is None:
        return None
    cleaned = _METRIC.sub("", heading).strip(" \t\r\n:-_/()[]%")
    if re.fullmatch(r"[A-Za-z0-9][\w. -]{1,60}", cleaned) and cleaned.casefold() not in ("score", "result", "metric", "performance"):
        return cleaned
    return None


def _system_from_heading(heading: str) -> str | None:
    metric, _ = _metric_spec(heading)
    if metric is None:
        return None
    cleaned = _METRIC.sub("", heading).strip(" \t\r\n:-_/()[]%")
    if re.fullmatch(r"[A-Za-z][\w.*+ -]{1,65}", cleaned):
        return cleaned
    return None


def _evidence(field: str, frag: SourceFragment, quote: str) -> dict[str, str]:
    # Direct substring from a single fragment, verified again by ground_record.
    return {"field": field, "fragment_id": frag.id, "quote": quote}


def _parse_one(frag: SourceFragment) -> tuple[list[dict[str, Any]], int]:
    lines = frag.text.splitlines()
    if not lines or not lines[0].strip().startswith("EXTRACTED TABLE ("):
        return [], 0
    header_lines = [line for line in lines if line.startswith("Columns: ")]
    if len(header_lines) != 1:
        return [], 0
    header_quote = header_lines[0]
    headers = [x.strip() for x in header_quote.removeprefix("Columns: ").split("|")]
    if not (2 <= len(headers) <= 60):
        return [], 0
    kinds = [_header_kind(h) for h in headers]
    system_cols = [i for i, k in enumerate(kinds) if k == "system"]
    dataset_cols = [i for i, k in enumerate(kinds) if k == "dataset"]
    if len(system_cols) > 1 or len(dataset_cols) > 1 or (not system_cols and not dataset_cols):
        return [], 0
    system_col = system_cols[0] if system_cols else None
    dataset_col = dataset_cols[0] if dataset_cols else None
    # A caption/metric must be present in THIS SAME fragment to be used.
    context_lines = [line for line in lines if line.startswith(("Metric: ", "Caption: "))]
    context_metric = None
    context_k = None
    context_quote = ""
    for line in context_lines:
        m, k = _metric_spec(line)
        if m is not None:
            if context_metric is not None and (context_metric, context_k) != (m, k):
                context_metric = None
                break
            context_metric, context_k, context_quote = m, k, line
    rows: list[dict[str, Any]] = []
    skipped = 0
    for row_line in lines:
        if not row_line.startswith("Row: "):
            continue
        cells = [x.strip() for x in row_line.removeprefix("Row: ").split("|")]
        if len(cells) != len(headers):
            skipped += 1
            continue
        if system_col is not None and not cells[system_col]:
            skipped += 1
            continue
        if dataset_col is not None and not cells[dataset_col]:
            skipped += 1
            continue
        for col, raw in enumerate(cells):
            if col == system_col or col == dataset_col:
                continue
            number = _NUM.fullmatch(raw)
            if number is None:
                continue
            value = float(number.group(1).replace(",", "."))
            # Numeric headers like "Time (ms)" must not masquerade as RAG metrics.
            head_metric, head_k = _metric_spec(headers[col])
            metric = head_metric or context_metric
            k = head_k if head_metric else context_k
            if system_col is not None and dataset_col is not None:
                system = cells[system_col]
                dataset = cells[dataset_col]
                dataset_quote = row_line
                system_quote = row_line
            elif system_col is not None:
                system = cells[system_col]
                dataset = _dataset_from_heading(headers[col])
                dataset_quote = header_quote
                system_quote = row_line
                # A dataset column without an explicit metric must remain incomplete,
                # never label numeric values as Exact Match by assumption.
            else:
                dataset = cells[dataset_col]
                system = _system_from_heading(headers[col])
                dataset_quote = row_line
                system_quote = header_quote
            if metric is None or not system or not dataset:
                skipped += 1
                continue
            # Header must support metric, unless explicit caption/metric line does.
            metric_quote = header_quote if head_metric else context_quote
            record: dict[str, Any] = {
                "rag_variant": system,
                "dataset_name": dataset,
                "metric_name": metric,
                "metric_value": value,
                "evidence": [
                    _evidence("rag_variant", frag, system_quote),
                    _evidence("dataset_name", frag, dataset_quote),
                    _evidence("metric_name", frag, metric_quote),
                    _evidence("metric_value", frag, row_line),
                ],
            }
            if k is not None:
                record["metric_k"] = k
                record["evidence"].append(_evidence("metric_k", frag, metric_quote))
            # Preserve published numeric scale. Percent only when literally given.
            if number.group(2) or "%" in headers[col]:
                record["metric_unit"] = "percent"
                record["evidence"].append(_evidence("metric_unit", frag, row_line if number.group(2) else header_quote))
            rows.append(record)
            if len(rows) >= _MAX_RECORDS:
                return rows, skipped
    return rows, skipped


def extract_rag_table_records(fragments: Iterable[SourceFragment], limit: int = _MAX_RECORDS) -> TableExtraction:
    """Parse only unambiguous header/row associations; no model and no persistence."""
    result: list[dict[str, Any]] = []
    table_count = skipped_rows = 0
    for frag in fragments:
        if not frag.text.startswith("EXTRACTED TABLE ("):
            continue
        table_count += 1
        if table_count > _MAX_TABLE_FRAGMENTS:
            break
        rows, skipped = _parse_one(frag)
        skipped_rows += skipped
        for row in rows:
            if len(result) >= max(1, min(limit, _MAX_RECORDS)):
                break
            result.append(row)
        if len(result) >= max(1, min(limit, _MAX_RECORDS)):
            break
    return TableExtraction(
        records=result,
        table_fragment_count=table_count,
        skipped_rows=skipped_rows,
        complete_context_count=len(result),
    )
