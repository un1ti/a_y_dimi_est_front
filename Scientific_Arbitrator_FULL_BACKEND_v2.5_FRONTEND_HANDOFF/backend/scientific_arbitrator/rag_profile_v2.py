"""RAG scientific profile v2: conservative, domain-aware validation and arbitration.

This module does not call an LLM, modify stored records, or infer experimental facts.
Missing metadata remains missing even if a quote contains relevant words.
"""
from __future__ import annotations

import re

from .common import ArbitrationResult, ValidationIssue, ValidationReport, Verdict
from .schemas import RAGResult


def canonical_metric(name: str) -> str:
    """Normalize a small group of well-known *aliases*, not distinct metrics."""
    n = re.sub(r"[\s_-]+", "", name.strip().lower())
    return {"em": "exactmatch", "exactmatch": "exactmatch", "hits": "hit", "hitrate": "hit"}.get(n, n)


# Only cut-off-dependent metric families require @k for unambiguous reporting.
CUTOFF_METRICS = {"recall", "precision", "hit", "ndcg", "map"}


def needs_k(metric: str) -> bool:
    return canonical_metric(metric) in CUTOFF_METRICS


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _equal(a: object, b: object) -> bool:
    return str(a).strip().casefold() == str(b).strip().casefold()


def validate_rag_v2(record: RAGResult) -> ValidationReport:
    issues: list[ValidationIssue] = []

    def warn(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message, severity="warning"))

    if not record.evidence:
        warn("EVIDENCE_MISSING", "evidence", "No source evidence attached to this record.")
    if needs_k(record.metric) and record.k is None:
        warn("K_UNSPECIFIED", "k", f"Metric {record.metric!r} requires an evaluation cutoff k.")
    if _missing(record.dataset):
        warn("DATASET_UNSPECIFIED", "dataset", "Evaluation dataset is not specified in the structured record.")
    if _missing(record.evaluation_protocol):
        warn("PROTOCOL_UNSPECIFIED", "evaluation_protocol", "Evaluation protocol is not specified.")
    if _missing(record.split):
        warn("SPLIT_UNSPECIFIED", "split", "Dataset evaluation split is not specified.")
    if _missing(record.system_id):
        warn("SYSTEM_UNSPECIFIED", "system_id", "RAG system or variant is not identified.")
    return ValidationReport(valid=True, issues=issues)


def arbitrate_rag_v2(first: RAGResult, second: RAGResult) -> ArbitrationResult:
    """Compare benchmark conditions, not model identity.

    This intentionally does not require retriever, reranker, embedding model, LLM,
    or chunking to match: varying these can be the *purpose* of a benchmark.
    """
    incompatible: list[str] = []
    missing: list[str] = []
    compared: list[str] = []
    reasons: list[str] = []

    a_metric, b_metric = canonical_metric(first.metric), canonical_metric(second.metric)
    compared.append("metric")
    if a_metric != b_metric:
        incompatible.append("metric")
        reasons.append(f"Different evaluation metrics: {first.metric!r} vs {second.metric!r}.")

    if needs_k(first.metric) or needs_k(second.metric):
        if first.k is None or second.k is None:
            missing.append("k")
        else:
            compared.append("k")
            if first.k != second.k:
                incompatible.append("k")
                reasons.append(f"Different evaluation cutoffs: k={first.k} vs k={second.k}.")

    for field in ("dataset", "evaluation_protocol", "split"):
        left, right = getattr(first, field), getattr(second, field)
        if _missing(left) or _missing(right):
            missing.append(field)
        else:
            compared.append(field)
            if not _equal(left, right):
                incompatible.append(field)
                reasons.append(f"Different {field}: {left!r} vs {right!r}.")

    if incompatible:
        if missing:
            reasons.append("Also missing context: " + ", ".join(missing) + ".")
        return ArbitrationResult(domain="rag", verdict=Verdict.INCOMPARABLE,
                                 reasons=reasons, blocking_fields=incompatible + missing,
                                 compared_fields=compared)
    if missing:
        return ArbitrationResult(domain="rag", verdict=Verdict.INSUFFICIENT_DATA,
                                 reasons=["Insufficient benchmark context: " + ", ".join(missing) + "."],
                                 blocking_fields=missing, compared_fields=compared)
    return ArbitrationResult(domain="rag", verdict=Verdict.COMPARABLE,
                             reasons=["Matching metric, cutoff where relevant, dataset, protocol and split; "
                                      "model differences may be the subject of comparison."],
                             compared_fields=compared)
