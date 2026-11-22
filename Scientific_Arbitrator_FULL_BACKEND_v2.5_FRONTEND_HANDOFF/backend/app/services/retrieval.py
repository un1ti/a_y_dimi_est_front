"""Lightweight lexical fragment selection for the two scientific domains.

This is intentionally NOT vector retrieval. It prioritizes experimental tables
and numeric observations, keeping entire fragments within a prompt budget.
"""
from __future__ import annotations
import re

from app.db.models import SourceFragment
from app.schemas.domain import Domain

KEYWORDS: dict[str, tuple[str, ...]] = {
    "solar": ("pce", "efficiency", "voc", "jsc", "fill factor", "ff", "perovskite", "cigs", "cdte", "solar", "bandgap", "device", "am1.5", "area", "table"),
    "rag": ("rag", "retrieval", "retriever", "embedding", "chunk", "top_k", "top-k", "generator", "recall", "mrr", "ndcg", "benchmark", "dataset", "evaluation", "exact match", "nq", "triviaqa", "table"),
}


def _score(fragment: SourceFragment, domain: Domain) -> int:
    text = fragment.text.lower()
    score = sum(min(len(re.findall(re.escape(term), text)), 5) for term in KEYWORDS[domain])
    score += 12 if text.startswith("extracted table") else 0
    score += 4 if re.search(r"\btable\s*[12]\b", text) else 0
    # Numeric result fragments are more informative than general intro passages.
    score += min(12, len(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", text)) // 2)
    if domain == "solar":
        score += 6 if all(term in text for term in ("pce", "voc", "jsc")) else 0
        score += 3 if any(term in text for term in ("control", "modified", "target")) else 0
    else:
        score += 6 if ("rag-seq" in text or "rag-token" in text) and ("nq" in text or "exact match" in text) else 0
    return score


def find_relevant_fragments(
    fragments: list[SourceFragment], domain: Domain, top_k: int = 15,
    prompt_budget: int = 18000,
) -> list[SourceFragment]:
    """Select whole fragments only; never truncate a source in the LLM prompt."""
    if not fragments:
        return []
    ranked = sorted(enumerate(fragments), key=lambda item: (-_score(item[1], domain), item[0]))
    selected: list[SourceFragment] = []
    consumed = 0
    for _, frag in ranked:
        # Room for FRAGMENT_ID and PAGE in every prompt entry.
        cost = len(frag.text) + 120
        if consumed + cost > prompt_budget:
            continue
        selected.append(frag)
        consumed += cost
        if len(selected) >= top_k:
            break
    return selected
