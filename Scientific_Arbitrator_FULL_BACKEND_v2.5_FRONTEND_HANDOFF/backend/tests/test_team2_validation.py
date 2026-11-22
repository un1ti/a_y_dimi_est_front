import pytest
from pydantic import ValidationError
from scientific_arbitrator import SolarResult, RAGResult, validate_solar, validate_rag


def test_solar_pce_out_of_range_rejected():
    with pytest.raises(ValidationError):
        SolarResult(study_id="S1", metric="PCE", value=101, unit="%")


def test_solar_valid_record_and_missing_context_warnings():
    record = SolarResult(study_id="S1", metric="PCE", value=21.4, unit="%")
    report = validate_solar(record)
    assert report.valid is True
    assert "STATISTIC_UNSPECIFIED" in {i.code for i in report.issues}


def test_rag_recall_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RAGResult(study_id="R1", metric="Recall", value=1.2, k=5)


def test_rag_missing_k_warned():
    record = RAGResult(study_id="R1", metric="Recall", value=0.82)
    report = validate_rag(record)
    assert "K_UNSPECIFIED" in {i.code for i in report.issues}


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        SolarResult(study_id="S1", metric="PCE", value=20, unit="%", invented_field=42)
