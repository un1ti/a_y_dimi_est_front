"""Conservative, source-supported RAG dataset recovery; no LLM and no DB writes."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Extend the dictionary only when project maintainers verify a benchmark alias.
DATASET_ALIASES = {
    'HotpotQA': (r'\bhotpot\s*qa\b',),
    '2Wiki': (r'\b2\s*wiki(?:multihopqa)?\b', r'\b2wikimultihopqa\b'),
    'MuSiQue': (r'\bmusique\b',),
}
NUMBER_RE = re.compile(r'(?<![\w.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![\w.])')


def _names(quote: str) -> set[str]:
    return {name for name, patterns in DATASET_ALIASES.items()
            if any(re.search(pattern, quote, flags=re.I) for pattern in patterns)}


def _contains_exact_value(quote: str, value: object) -> bool:
    try:
        expected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    for match in NUMBER_RE.finditer(quote):
        try:
            if Decimal(match.group()) == expected:
                return True
        except InvalidOperation:
            pass
    return False


def recover_dataset(data: dict, evidence: list[dict]) -> tuple[str | None, str]:
    """Infer only when a verified metric-value quote unambiguously names a dataset.

    This associates the number and dataset *within a quote*, not necessarily a
    table column. It is a candidate association for benchmarking, not a proof
    that the table-cell row/column mapping was reconstructed correctly.
    """
    existing = data.get('dataset_name')
    if isinstance(existing, str) and existing.strip():
        return existing.strip(), 'original'
    value = data.get('metric_value')
    if value is None:
        return None, 'missing_metric_value'
    candidates: set[str] = set()
    ambiguous = False
    for item in evidence:
        if item.get('field') != 'metric_value' or item.get('verification') != 'quote_matched':
            continue
        quote = item.get('quote') or ''
        if not _contains_exact_value(quote, value):
            continue
        matches = _names(quote)
        if len(matches) > 1:
            ambiguous = True
        candidates.update(matches)
    if not ambiguous and len(candidates) == 1:
        return next(iter(candidates)), 'recovered_from_verified_metric_quote'
    if ambiguous or len(candidates) > 1:
        return None, 'ambiguous_verified_quote'
    return None, 'no_unambiguous_verified_quote'
