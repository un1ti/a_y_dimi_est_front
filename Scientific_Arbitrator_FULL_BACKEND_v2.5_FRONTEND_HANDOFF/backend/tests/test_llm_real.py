import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.services.grounding import ground_record
from app.services.llm import LLMError, OpenAICompatibleProvider
from app.schemas.domain import RagFinding, SolarFinding


def sample_fragment(text="RAG-Seq. | NQ | 44.5"):
    return SimpleNamespace(id="source-123", page=6, text=text)


def test_chat_completions_provider_sends_real_api_contract(monkeypatch):
    seen = {}

    def respond(self, url, *, json=None, headers=None, **kw):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        content = {
            "records": [{
                "rag_variant": "RAG-Seq.", "dataset_name": "NQ", "metric_name": "Exact Match",
                "metric_value": 44.5,
                "evidence": [{"field": "metric_value", "fragment_id": "source-123", "quote": "44.5"}],
            }]
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": __import__('json').dumps(content)}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", respond)
    settings = Settings(llm_mode="openai", llm_model="test-model", llm_base_url="https://api.example.com/v1", llm_api_key="test-token")
    response = OpenAICompatibleProvider(settings).extract("rag", [sample_fragment()])
    assert response["records"][0]["metric_value"] == 44.5
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-token"
    assert seen["json"]["response_format"] == {"type": "json_object"}
    assert "RAG-Sequence" in seen["json"]["messages"][0]["content"]
    assert "FRAGMENT_ID=source-123" in seen["json"]["messages"][1]["content"]


def test_api_key_required_for_remote_host():
    settings = Settings(llm_mode="openai", llm_model="test-model", llm_base_url="https://api.example.com/v1", llm_api_key="")
    with pytest.raises(LLMError, match="LLM_API_KEY is empty"):
        OpenAICompatibleProvider(settings).extract("rag", [sample_fragment()])


def test_model_bad_evidence_is_removed_not_saved():
    model = SolarFinding(
        pce_pct=21.5, voc_v=1.193,
        evidence=[
            {"field": "pce_pct", "fragment_id": "source-123", "quote": "PCE 21.50"},
            {"field": "voc_v", "fragment_id": "source-123", "quote": "VOC 1.250"},
        ],
    )
    src = sample_fragment("Modified solar cell: PCE 21.50; VOC 1.250")
    data, evidence, dropped = ground_record(model, {"source-123": src})
    assert data["pce_pct"] == 21.5
    assert data["voc_v"] is None  # cited quote supports 1.250, NOT 1.193
    assert "voc_v" in dropped
    assert [x["field"] for x in evidence] == ["pce_pct"]


def test_unit_conversion_from_ff_fraction_allowed():
    model = SolarFinding(ff_pct=80.0, evidence=[{"field": "ff_pct", "fragment_id": "source-123", "quote": "FF is 0.80"}])
    data, evidence, dropped = ground_record(model, {"source-123": sample_fragment("FF is 0.80")})
    assert data["ff_pct"] == 80.0
    assert not dropped
    assert evidence


def test_invalid_fragment_id_cannot_ground_result():
    model = RagFinding(metric_value=44.5, evidence=[{"field": "metric_value", "fragment_id": "invented", "quote": "44.5"}])
    data, evidence, dropped = ground_record(model, {"source-123": sample_fragment()})
    assert data["metric_value"] is None
    assert evidence == []
    assert dropped == ["metric_value"]


def test_http_unauthorized_is_actionable_without_leaking_content(monkeypatch):
    def respond(self, url, **kw):
        return httpx.Response(401, text="SECRET_INTERNAL_ERROR_BODY", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", respond)
    settings = Settings(llm_mode="openai", llm_model="test-model", llm_base_url="https://api.example.com/v1", llm_api_key="dummy")
    with pytest.raises(LLMError) as exc:
        OpenAICompatibleProvider(settings).extract("solar", [sample_fragment()])
    assert "401" in str(exc.value)
    assert "SECRET_INTERNAL_ERROR_BODY" not in str(exc.value)


def test_real_mode_full_http_flow_rag(client, monkeypatch):
    """End-to-end OpenAI-compatible HTTP contract, with a deterministic fake provider."""
    from dataclasses import replace
    from .conftest import pdf_bytes

    upload = client.post("/api/v1/documents", data={"domain": "rag"}, files={"file": ("paper.pdf", pdf_bytes("RAG-Sequence NQ Exact Match = 44.5"), "application/pdf")})
    assert upload.status_code == 201
    publication_id = upload.json()["id"]
    frag_id = client.get(f"/api/v1/documents/{publication_id}/fragments").json()[0]["id"]
    client.app.state.settings = replace(client.app.state.settings, llm_mode="openai", llm_model="test-real-provider", llm_base_url="https://provider.invalid/v1", llm_api_key="test-key")
    original = httpx.Client.post

    def respond(self, url, **kwargs):
        if str(url).startswith("https://provider.invalid/"):
            payload = {"records": [{
                "rag_variant": "RAG-Sequence", "dataset_name": "NQ", "metric_name": "Exact Match", "metric_value": 44.5,
                "evidence": [
                    {"field": "rag_variant", "fragment_id": frag_id, "quote": "RAG-Sequence"},
                    {"field": "dataset_name", "fragment_id": frag_id, "quote": "NQ"},
                    {"field": "metric_name", "fragment_id": frag_id, "quote": "Exact Match"},
                    {"field": "metric_value", "fragment_id": frag_id, "quote": "44.5"},
                ],
            }]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}, request=httpx.Request("POST", url))
        return original(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", respond)
    status = client.get("/api/v1/llm/status").json()
    assert status["mode"] == "openai" and status["configured"]
    analyzed = client.post(f"/api/v1/documents/{publication_id}/analyze")
    assert analyzed.status_code == 202
    result = client.get(f"/api/v1/documents/{publication_id}/results").json()
    assert result["latest_job"]["status"] == "done", result
    assert result["latest_job"]["llm_mode"] == "openai"
    assert result["records"][0]["data"]["metric_value"] == 44.5
    assert {e["field"] for e in result["records"][0]["evidence"]} == {"rag_variant", "dataset_name", "metric_name", "metric_value"}


def test_real_mode_full_http_flow_solar(client, monkeypatch):
    """Model links four metrics to one experimental device; values stay together."""
    from dataclasses import replace
    from .conftest import pdf_bytes

    paper_text = "Target cell PCE = 21.50%, Voc = 1.193 V, Jsc = 22.59 mA/cm2, FF = 79.80%."
    upload = client.post("/api/v1/documents", data={"domain": "solar"}, files={"file": ("solar.pdf", pdf_bytes(paper_text), "application/pdf")})
    assert upload.status_code == 201
    publication_id = upload.json()["id"]
    frag_id = client.get(f"/api/v1/documents/{publication_id}/fragments").json()[0]["id"]
    client.app.state.settings = replace(client.app.state.settings, llm_mode="openai", llm_model="test-real-provider", llm_base_url="https://provider.invalid/v1", llm_api_key="test-key")
    original = httpx.Client.post

    def respond(self, url, **kwargs):
        if str(url).startswith("https://provider.invalid/"):
            payload = {"records": [{
                "device_label": "Target cell", "pce_pct": 21.50, "voc_v": 1.193,
                "jsc_ma_cm2": 22.59, "ff_pct": 79.80,
                "evidence": [
                    {"field": "device_label", "fragment_id": frag_id, "quote": "Target cell"},
                    {"field": "pce_pct", "fragment_id": frag_id, "quote": "PCE = 21.50%"},
                    {"field": "voc_v", "fragment_id": frag_id, "quote": "Voc = 1.193 V"},
                    {"field": "jsc_ma_cm2", "fragment_id": frag_id, "quote": "Jsc = 22.59 mA/cm2"},
                    {"field": "ff_pct", "fragment_id": frag_id, "quote": "FF = 79.80%"},
                ],
            }]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}, request=httpx.Request("POST", url))
        return original(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", respond)
    analyzed = client.post(f"/api/v1/documents/{publication_id}/analyze")
    assert analyzed.status_code == 202
    result = client.get(f"/api/v1/documents/{publication_id}/results").json()
    assert result["latest_job"]["status"] == "done", result
    records = result["records"]
    assert len(records) == 1
    for name, val in (("pce_pct", 21.5), ("voc_v", 1.193), ("jsc_ma_cm2", 22.59), ("ff_pct", 79.8)):
        assert records[0]["data"][name] == val
    assert len(records[0]["evidence"]) == 5
