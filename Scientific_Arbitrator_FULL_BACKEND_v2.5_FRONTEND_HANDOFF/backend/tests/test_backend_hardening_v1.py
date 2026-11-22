"""Regression tests for four backend hardening stages. No network/LLM required."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scientific_arbitrator import SolarResult, Verdict, arbitrate_solar, validate_solar
from scientific_arbitrator.solar_profile_v2 import expected_pce_pct
from app.api.report_routes import _safe_csv_cell
from app.services.extraction_profile import schema_for_domain, select_scientific_fragments
from .conftest import pdf_bytes


def _solar(**overrides):
    data = dict(study_id="study", metric="PCE", value=15.3, unit="%",
                statistic="best", absorber_material="perovskite",
                architecture="n-i-p", measurement_conditions="AM1.5G",
                scan_direction="reverse", active_area_cm2=0.1,
                voc_v=0.982, jsc_ma_cm2=17.9, ff_pct=87.04,
                light_intensity_mw_cm2=100.0)
    data.update(overrides)
    return SolarResult(**data)


def test_solar_equation_100_mw_cm2():
    expected = expected_pce_pct(0.982, 17.9, 87.04, 100)
    assert expected == pytest.approx(15.301, abs=0.01)
    report = validate_solar(_solar())
    assert report.valid is True
    assert "PCE_PHYSICAL_INCONSISTENCY" not in {issue.code for issue in report.issues}
    assert "PCE_FORMULA_NOT_CHECKED" not in {issue.code for issue in report.issues}


def test_solar_mismatch_flagged_as_error():
    report = validate_solar(_solar(value=24.0))
    assert report.valid is False
    assert "PCE_PHYSICAL_INCONSISTENCY" in {i.code for i in report.issues}


def test_solar_unknown_irradiance_never_assumed():
    report = validate_solar(_solar(light_intensity_mw_cm2=None))
    assert report.valid is True
    assert "PCE_FORMULA_NOT_CHECKED" in {i.code for i in report.issues}


def test_solar_materials_can_be_comparison_subject():
    a = _solar()
    b = _solar(study_id="study2", value=15.0, absorber_material="CIGS", architecture="p-i-n")
    result = arbitrate_solar(a, b)
    assert result.verdict == Verdict.COMPARABLE
    assert "absorber_material" not in result.blocking_fields


def test_solar_measurement_conditions_mismatch_blocks():
    a = _solar()
    b = _solar(study_id="study2", light_intensity_mw_cm2=80)
    result = arbitrate_solar(a, b)
    assert result.verdict == Verdict.INCOMPARABLE
    assert "light_intensity_mw_cm2" in result.blocking_fields


def test_compact_schema_is_real_subset(monkeypatch):
    monkeypatch.setenv("RAG_COMPACT_SCHEMA", "true")
    schema = schema_for_domain("rag")
    assert schema["properties"]["records"]["maxItems"] == 8
    fields = schema["properties"]["records"]["items"]["properties"]
    assert "evidence" in fields and "metric_value" in fields and "dataset_name" in fields
    assert "retriever_model" in fields
    assert "invented_field" not in fields
    from app.schemas.domain import RagOutput
    record = {"rag_variant": "GraphRAG", "dataset_name": "HotpotQA", "metric_name": "Exact Match", "metric_value": 0.556,
              "evidence": [{"field": "metric_value", "fragment_id": "frag", "quote": "HotpotQA 0.556"}]}
    assert RagOutput.model_validate({"records": [record]}).records[0].metric_value == pytest.approx(.556)
    assert schema_for_domain("solar") != schema


def test_fragment_budget_is_bounded(monkeypatch):
    monkeypatch.setenv("RAG_TOP_K", "1")
    monkeypatch.setenv("RAG_PROMPT_BUDGET", "500")
    frags = [SimpleNamespace(text="RAG Recall@5 = 0.80", page=1), SimpleNamespace(text="RAG Recall@5 = 0.82", page=2)]
    settings = SimpleNamespace(max_prompt_chars=5000)
    chosen = select_scientific_fragments(frags, "rag", settings)
    assert len(chosen) == 1
    chosen_solar = select_scientific_fragments(frags, "solar", settings)
    assert len(chosen_solar) >= 1


def test_csv_formula_injection_guard():
    for text in ("=SUM(A1:A2)", "-1+2", "+1+2", "@danger", "\t=1"):
        assert _safe_csv_cell(text).startswith("'")
    assert _safe_csv_cell("GraphRAG") == "GraphRAG"


def test_quality_and_report_api(client):
    r = client.post("/api/v1/documents", data={"domain": "solar"},
                    files={"file": ("test.pdf", pdf_bytes("Solar cell PCE = 15.3%, Voc = 0.982 V, Jsc = 17.9 mA/cm2, FF = 87.04%."), "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()["id"]
    assert client.post(f"/api/v1/documents/{doc}/analyze").status_code == 202
    result = client.get(f"/api/v1/documents/{doc}/results").json()
    assert result["latest_job"]["status"] == "done"
    quality = client.get(f"/api/v1/scientific/quality/{doc}")
    assert quality.status_code == 200, quality.text
    q = quality.json()
    assert q["domain"] == "solar" and q["total"] >= 1
    assert q["ready_for_comparison_count"] == 0  # no irradiance in source
    assert any("PCE_FORMULA_NOT_CHECKED" in rec["issues"] for rec in q["records"])
    report = client.get(f"/api/v1/scientific/reports/{doc}")
    assert report.status_code == 200
    assert report.json()["total"] >= 1
    assert report.json()["results"][0]["evidence"]
    csv_report = client.get(f"/api/v1/scientific/reports/{doc}", params={"format": "csv"})
    assert csv_report.status_code == 200
    assert csv_report.content.startswith("\ufeff".encode("utf-8"))
    assert "record_id,domain" in csv_report.text
    assert client.get("/api/v1/scientific/quality/not-found").status_code == 404


def test_openapi_contains_new_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/scientific/quality/{publication_id}" in paths
    assert "/api/v1/scientific/reports/{publication_id}" in paths
