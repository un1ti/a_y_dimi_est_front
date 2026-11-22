"""Verify model citations, and remove unsupported field values before persistence.

This establishes SOURCE TRACEABILITY, not scientific correctness. Scientific
validation belongs to developer #2 and has a separate status.
"""
from __future__ import annotations

import math
import re
from typing import Any

from app.db.models import SourceFragment
from app.schemas.domain import FindingBase


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("\u00ad", "").strip().casefold()


def numeric_supported(field: str, value: float | int, quote: str) -> bool:
    """Check the source quote actually contains the cited numerical quantity."""
    numbers = []
    for match in re.finditer(r"(?<![\w.,])[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?!\w)", quote):
        try:
            numbers.append(float(match.group(0).replace(",", ".")))
        except ValueError:
            continue
    for raw in numbers:
        if math.isclose(float(value), raw, abs_tol=1e-4, rel_tol=1e-5):
            return True
        # Specific conversion allowed by the Solar schema when FF was stated
        # in 0-1 scale but output ff_pct is 0-100.
        if field == "ff_pct" and 0 <= raw <= 1 and math.isclose(float(value), 100 * raw, abs_tol=0.02):
            return True
    return False


def ground_record(
    finding: FindingBase, fragments: dict[str, SourceFragment]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Return sanitized data, verified citations and names of removed fields."""
    original = finding.model_dump(exclude={"evidence"})
    verified_fields: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for ref in finding.evidence:
        fragment = fragments.get(ref.fragment_id)
        if fragment is None or ref.field not in original or original[ref.field] is None:
            continue
        if normalized(ref.quote) not in normalized(fragment.text):
            continue
        value = original[ref.field]
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if not numeric_supported(ref.field, value, ref.quote):
                continue
        verified_fields.add(ref.field)
        evidence.append({
            "field": ref.field,
            "fragment_id": ref.fragment_id,
            "page": fragment.page,
            "quote": ref.quote,
            "verification": "quote_matched",
        })
    ungrounded = [field for field, value in original.items() if value is not None and field not in verified_fields]
    sanitized = {field: value if field in verified_fields else None for field, value in original.items()}
    return sanitized, evidence, ungrounded
