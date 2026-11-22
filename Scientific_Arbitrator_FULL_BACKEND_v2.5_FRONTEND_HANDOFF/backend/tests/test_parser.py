import pytest
from app.services.pdf_parser import split_text, parse_pdf, PDFParseError
from .conftest import pdf_bytes


def test_chunking_short_and_long():
    assert split_text(" abc ") == ["abc"]
    chunks = split_text("alpha " * 900, chunk_size=200, overlap=40)
    assert len(chunks) > 2
    assert all(len(x) <= 200 for x in chunks)


def test_pdf_parser_and_validation():
    parsed = parse_pdf(pdf_bytes("Hello RAG top_k=5"))
    assert parsed.page_count == 1 and parsed.text_status == "ok"
    with pytest.raises(PDFParseError):
        parse_pdf(b"false PDF")
    with pytest.raises(PDFParseError):
        parse_pdf(pdf_bytes("sample"), max_pages=0)
