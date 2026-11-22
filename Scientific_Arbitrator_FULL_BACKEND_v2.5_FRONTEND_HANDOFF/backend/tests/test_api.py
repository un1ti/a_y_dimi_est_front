from .conftest import pdf_bytes


def test_health_domains(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    codes = {x["code"] for x in client.get("/api/v1/domains").json()}
    assert codes == {"rag", "solar"}


def test_rag_upload_analyze_results_evidence(client):
    content = pdf_bytes("Our RAG uses top_k=5, chunk_size=512 and Recall@5 = 0.82 on NQ.")
    res = client.post("/api/v1/documents", data={"domain": "rag"}, files={"file": ("study.pdf", content, "application/pdf")})
    assert res.status_code == 201, res.text
    doc = res.json()
    assert doc["fragment_count"] >= 1 and doc["page_count"] == 1
    doc_id = doc["id"]
    assert client.get(f"/api/v1/documents/{doc_id}/file").content.startswith(b"%PDF-")
    fragments = client.get(f"/api/v1/documents/{doc_id}/fragments").json()
    assert fragments[0]["page"] == 1
    job_res = client.post(f"/api/v1/documents/{doc_id}/analyze")
    assert job_res.status_code == 202, job_res.text
    job_id = job_res.json()["id"]
    completed = client.get(f"/api/v1/jobs/{job_id}").json()
    assert completed["status"] == "done", completed
    results = client.get(f"/api/v1/documents/{doc_id}/results").json()
    assert results["records"]
    record = results["records"][0]
    assert record["data"]["top_k"] == 5
    assert record["data"]["metric_k"] == 5
    assert record["data"]["metric_value"] == 0.82
    assert record["validation_status"] == "not_run"
    evidence = client.get(f"/api/v1/results/{record['id']}/evidence").json()
    assert evidence and all(e["verification"] == "quote_matched" and e["page"] == 1 for e in evidence)
    assert len(client.get("/api/v1/exports/json?domain=rag").json()["records"]) == 1


def test_solar_upload_analyze(client):
    content = pdf_bytes("Perovskite cell: PCE = 21.4%, Voc = 1.08 V, Jsc = 22.5 mA/cm2, FF = 76%.")
    upload = client.post("/api/v1/documents", data={"domain": "solar"}, files={"file": ("solar.pdf", content, "application/pdf")})
    assert upload.status_code == 201, upload.text
    pid = upload.json()["id"]
    client.post(f"/api/v1/documents/{pid}/analyze")
    record = client.get(f"/api/v1/documents/{pid}/results").json()["records"][0]
    assert record["domain"] == "solar"
    assert record["data"]["pce_pct"] == 21.4
    assert record["data"]["voc_v"] == 1.08
    assert record["data"]["jsc_ma_cm2"] == 22.5
    assert record["data"]["ff_pct"] == 76.0


def test_repeated_upload_is_deduplicated(client):
    content = pdf_bytes("top_k=7 and Recall@7 = 0.7")
    args = dict(data={"domain": "rag"}, files={"file": ("a.pdf", content, "application/pdf")})
    first = client.post("/api/v1/documents", **args)
    second = client.post("/api/v1/documents", **args)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


def test_invalid_pdf_and_missing_document(client):
    res = client.post("/api/v1/documents", data={"domain": "solar"}, files={"file": ("bad.pdf", b"not a pdf", "application/pdf")})
    assert res.status_code == 422
    assert client.get("/api/v1/documents/missing").status_code == 404
    assert client.post("/api/v1/documents/missing/analyze").status_code == 404


def test_no_text_pdf_prevents_analysis(client):
    import pymupdf
    with pymupdf.open() as pdf:
        pdf.new_page()
        content = pdf.tobytes()
    res = client.post("/api/v1/documents", data={"domain": "rag"}, files={"file": ("blank.pdf", content, "application/pdf")})
    assert res.status_code == 201
    assert res.json()["text_status"] == "no_text"
    assert client.post(f"/api/v1/documents/{res.json()['id']}/analyze").status_code == 422
