"""Integration tests against the existing FastAPI/SQLite backend (mock LLM only)."""
from .conftest import pdf_bytes


def _document(client, *, domain: str, text: str):
    r = client.post("/api/v1/documents", data={"domain": domain}, files={"file": ("a.pdf", pdf_bytes(text), "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()["id"]
    assert client.post(f"/api/v1/documents/{doc}/analyze").status_code == 202
    data = client.get(f"/api/v1/documents/{doc}/results").json()
    assert data["latest_job"]["status"] == "done", data
    assert data["records"]
    return data["records"][0]["id"]


def test_solar_validation_route(client):
    rec_id = _document(client, domain="solar", text="Perovskite cell PCE = 21.4%, Voc = 1.08 V, Jsc = 22.5 mA/cm2, FF = 76%.")
    r = client.get(f"/api/v1/scientific/results/{rec_id}/validate")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["normalized_record"]["metric"] == "PCE"
    assert data["normalized_record"]["value"] == 21.4
    assert data["validation"]["valid"] is True
    assert data["normalized_record"]["evidence"]
    assert client.get(f"/api/v1/results/{rec_id}").json()["validation_status"] == "not_run"


def test_comparing_two_rag_records_in_different_docs(client):
    a = _document(client, domain="rag", text="Our RAG uses top_k=5 and Recall@5 = 0.82 on NQ.")
    b = _document(client, domain="rag", text="Our RAG uses top_k=10 and Recall@10 = 0.91 on NQ.")
    r = client.post("/api/v1/scientific/compare", json={"left_record_id": a, "right_record_id": b})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verdict"] == "incomparable", data
    assert "k" in data["blocking_fields"]


def test_compare_missing_record_returns_404(client):
    r = client.post("/api/v1/scientific/compare", json={"left_record_id": "missing", "right_record_id": "missing"})
    assert r.status_code == 404


def test_rag_without_metric_rejected(client):
    rec_id = _document(client, domain="rag", text="RAG uses top_k=5 and chunk_size=512 on NQ.")
    r = client.get(f"/api/v1/scientific/results/{rec_id}/validate")
    assert r.status_code == 422
