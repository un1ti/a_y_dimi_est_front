from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.db.models import Publication
from .conftest import pdf_bytes


def test_relative_data_dir_ignores_terminal_working_directory(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", "./.data")
    settings = Settings()
    assert settings.data_dir == (PROJECT_ROOT / ".data").resolve()


def test_uploaded_pdf_can_be_opened_after_legacy_absolute_path_is_stale(client):
    content = pdf_bytes("Recall@5 = 0.82")
    reply = client.post(
        "/api/v1/documents",
        data={"domain": "rag"},
        files={"file": ("study.pdf", content, "application/pdf")},
    )
    assert reply.status_code == 201
    publication_id = reply.json()["id"]
    with client.app.state.sessionmaker() as session:
        obj = session.get(Publication, publication_id)
        assert obj.stored_path == f"uploads/{publication_id}.pdf"
        # Simulate a previously created DB copied from a different machine.
        obj.stored_path = f"/Users/example/old-project/uploads/{publication_id}.pdf"
        session.commit()
    pdf_response = client.get(f"/api/v1/documents/{publication_id}/file")
    assert pdf_response.status_code == 200
    assert pdf_response.content == content
