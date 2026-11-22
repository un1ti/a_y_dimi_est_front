from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}", llm_mode="mock")
    with TestClient(create_app(settings)) as c:
        yield c


def pdf_bytes(text: str) -> bytes:
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 70), text, fontsize=11)
        return pdf.tobytes()
