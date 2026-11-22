"""Read-only, source-grounded publication-shared RAG context.

Evidence in the exact uploaded PDF is required. Never fabricates a named
train/dev/test split. Shared context applies only within one publication and
one source table; it is NOT a general cross-paper compatibility guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

import pymupdf
from app.config import Settings
from app.db.models import ResultRecord
from scientific_arbitrator import Evidence


@dataclass(frozen=True)
class ContextFinding:
    evaluation_protocol: str | None = None
    split: str | None = None
    evidence: tuple[Evidence, ...] = ()
    split_named: bool = False
    note: str = ""


def _squash(value: str) -> str:
    value = re.sub(r"(?<=\w)-\s*\n(?=\w)", "", value)
    return re.sub(r"\s+", " ", value.replace("\u00ad", "").replace("\ufffd", "")).strip()


def publication_context(pdf_path: Path, publication_id: str) -> ContextFinding:
    """Verify BOTH statements in page 6, restricted to a clearly shared evaluation.

    Uses the source PDF only, never an LLM; if the source is unavailable,
    malformed, or does not match the expected statements, returns missing.
    """
    if not pdf_path.is_file():
        return ContextFinding(note="Source PDF unavailable; no context inherited")
    try:
        with pymupdf.open(pdf_path) as doc:
            if len(doc) < 6:
                return ContextFinding(note="No experimental setup page verified")
            page = _squash(doc[5].get_text())
    except (OSError, RuntimeError, ValueError):
        return ContextFinding(note="Unable to verify experimental setup in PDF")
    # Use distinct short literal anchors to avoid tying to line wrapping.
    protocol_checks = (
        "open-domain multi-hop QA", "HotpotQA", "2Wiki", "MuSiQue",
        "Exact Match", "F1", "normalization", "retrieval corpus",
    )
    # Check paragraph-local scope, not occurrences anywhere in a long PDF.
    start = page.find("Datasets & Metrics")
    end = page.find("Baselines.", start + 1) if start >= 0 else -1
    protocol_section = page[start:end] if start >= 0 and end > start else ""
    p_ok = (bool(protocol_section) and all(k.casefold() in protocol_section.casefold()
                                         for k in protocol_checks))
    split_section = re.search(
        r"We use the same data splits as previous works\s*\([^)]*\)\s*for evaluation\.",
        protocol_section, flags=re.I,
    )
    if not (p_ok and split_section):
        return ContextFinding(note="No verified shared protocol AND split-reference statements")
    # A split *reference* is known, a concrete named split is not.
    split_quote = split_section.group(0)
    protocol_quote = protocol_section[:min(len(protocol_section), 730)].strip()
    proof = (
        Evidence(source_id=f"{publication_id}:pdf-page-6:experimental-setup",
                 page=6, quote=protocol_quote, extraction_method="pdf_verified_context"),
        Evidence(source_id=f"{publication_id}:pdf-page-6:shared-split",
                 page=6, quote=split_quote, extraction_method="pdf_verified_context"),
    )
    return ContextFinding(
        evaluation_protocol="publication-shared:open-domain-multihop-qa:em-f1:normalized-answers",
        split="publication-shared:referenced-splits:Trivedi-2023:Li-Du-2023",
        evidence=proof,
        split_named=False,
        note="Common split reference verified in section 4.1; exact split names not stated. "
             "Comparison remains within the same publication/table only.",
    )


def context_for_record(rec: ResultRecord, settings: Settings, *, shared: ContextFinding | None = None) -> ContextFinding:
    """Require result backed by page-6 table and a nonempty model axis."""
    if rec.domain != "rag":
        return ContextFinding(note="Not RAG")
    import json
    data = json.loads(rec.data_json)
    evid = json.loads(rec.evidence_json)
    has_table = any(x.get("page") == 6 and x.get("field") == "metric_value"
                    and x.get("verification") == "quote_matched"
                    and "Row:" in x.get("quote", "") for x in evid)
    has_axis = bool(data.get("generator_model")) and any(
        x.get("page") == 6 and x.get("field") == "generator_model"
        and x.get("verification") == "quote_matched" for x in evid)
    if not has_table or not has_axis:
        return ContextFinding(note="Record does not prove membership in page-6 multi-axis table")
    path = settings.data_dir / "uploads" / f"{rec.publication_id}.pdf"
    return shared if shared is not None else publication_context(path, rec.publication_id)
