"""Compat layer for a common Qwen RAG JSON mistake: evidence_ref vs evidence.

Only known evidence keys are converted; unknown scientific fields remain subject
 to Pydantic's strict validation. Never fabricate fragment identifiers or quotes.
"""
from __future__ import annotations

from typing import Any


def normalize_rag_payload(payload: Any) -> Any:
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return payload
    result = dict(payload)
    converted = []
    for record in payload["records"]:
        if not isinstance(record, dict) or "evidence_ref" not in record:
            converted.append(record)
            continue
        item = dict(record)
        legacy = item.pop("evidence_ref")
        candidates = legacy if isinstance(legacy, list) else [legacy]
        current = item.get("evidence")
        if current is None:
            current = []
        if not isinstance(current, list):
            # Leave a malformed evidence field intact to trigger Pydantic validation.
            converted.append(item)
            continue
        repaired = list(current)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            # Require all elements of a real source quote. No invented citations.
            if not all(isinstance(candidate.get(k), str) and candidate[k].strip()
                       for k in ("field", "fragment_id", "quote")):
                continue
            evidence = {k: candidate[k] for k in ("field", "fragment_id", "quote")}
            if evidence not in repaired:
                repaired.append(evidence)
        item["evidence"] = repaired
        converted.append(item)
    result["records"] = converted
    return result
