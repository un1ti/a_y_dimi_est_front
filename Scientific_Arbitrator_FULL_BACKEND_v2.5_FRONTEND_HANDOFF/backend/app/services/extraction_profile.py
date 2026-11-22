"""Opt-in bounded retrieval and compact RAG prompt schema for small local models.

This reduces prompt pressure but cannot guarantee a faster model response.
The output remains subject to RagOutput validation and Evidence Trace grounding.
"""
from __future__ import annotations

import os
from typing import Any

from app.schemas.domain import RagOutput, SolarOutput
from app.services.retrieval import find_relevant_fragments


def _int_env(name: str, fallback: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name, str(fallback)))))
    except (TypeError, ValueError):
        return fallback


def select_scientific_fragments(fragments: list, domain: str, settings: Any) -> list:
    if domain == "rag":
        top_k = _int_env("RAG_TOP_K", 4, 1, 16)
        budget = min(settings.max_prompt_chars,
                     _int_env("RAG_PROMPT_BUDGET", 2500, 500, 25000))
    else:
        top_k, budget = 16, settings.max_prompt_chars
    return find_relevant_fragments(fragments, domain, top_k=top_k, prompt_budget=budget)


_RAG_FIELDS: dict[str, dict] = {
    "rag_variant": {"type": ["string", "null"]},
    "config_label": {"type": ["string", "null"]},
    "dataset_name": {"type": ["string", "null"]},
    "data_split": {"type": ["string", "null"]},
    "evaluation_protocol": {"type": ["string", "null"]},
    "metric_name": {"type": ["string", "null"]},
    "metric_value": {"type": ["number", "null"]},
    "metric_unit": {"type": ["string", "null"]},
    "metric_k": {"type": ["integer", "null"]},
    "retrieval_method": {"type": ["string", "null"]},
    "retriever_model": {"type": ["string", "null"]},
    "generator_model": {"type": ["string", "null"]},
    "embedding_model": {"type": ["string", "null"]},
}


def schema_for_domain(domain: str) -> dict:
    if domain != "rag" or os.getenv("RAG_COMPACT_SCHEMA", "false").lower() not in {"1", "true", "yes"}:
        return (SolarOutput if domain == "solar" else RagOutput).model_json_schema()
    return {
        "type": "object", "additionalProperties": False,
        "properties": {"records": {
            "type": "array", "maxItems": _int_env("RAG_PROMPT_MAX_RECORDS", 8, 1, 30),
            "items": {"type": "object", "additionalProperties": False,
                      "properties": {**_RAG_FIELDS, "evidence": {
                          "type": "array", "items": {"type": "object", "additionalProperties": False,
                              "properties": {"field": {"type": "string"},
                                             "fragment_id": {"type": "string"},
                                             "quote": {"type": "string"}},
                              "required": ["field", "fragment_id", "quote"]}}},
                      "required": ["evidence"]}}},
        "required": ["records"],
    }
