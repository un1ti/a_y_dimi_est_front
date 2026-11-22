from app.services.rag_output_compat import normalize_rag_payload
from app.schemas.domain import RagOutput
import pytest
from pydantic import ValidationError


def test_alias_single_valid_evidence():
    raw = {"records": [{"dataset_name": "HotpotQA", "evidence_ref": {
        "field": "dataset_name", "fragment_id": "fragment-123", "quote": "HotpotQA"}}]}
    out = RagOutput.model_validate(normalize_rag_payload(raw))
    assert out.records[0].evidence[0].fragment_id == "fragment-123"


def test_alias_list_and_existing_evidence():
    ev = {"field": "metric_value", "fragment_id": "f1", "quote": "0.86"}
    raw = {"records": [{"metric_value": 0.86, "evidence": [ev], "evidence_ref": [ev]}]}
    out = RagOutput.model_validate(normalize_rag_payload(raw))
    assert len(out.records[0].evidence) == 1


def test_bad_alias_never_fabricates_evidence():
    raw = {"records": [{"dataset_name": "HotpotQA", "evidence_ref": {"field": "dataset_name", "quote": "HotpotQA"}}]}
    out = RagOutput.model_validate(normalize_rag_payload(raw))
    assert not out.records[0].evidence


def test_unknown_scientific_fields_still_rejected():
    raw = {"records": [{"not_a_scientific_field": 2, "evidence_ref": {"field": "a", "fragment_id": "f", "quote": "q"}}]}
    with pytest.raises(ValidationError):
        RagOutput.model_validate(normalize_rag_payload(raw))


def test_original_is_unmodified():
    raw = {"records": [{"evidence_ref": {"field": "x", "fragment_id": "f", "quote": "q"}}]}
    normalize_rag_payload(raw)
    assert "evidence_ref" in raw["records"][0]
