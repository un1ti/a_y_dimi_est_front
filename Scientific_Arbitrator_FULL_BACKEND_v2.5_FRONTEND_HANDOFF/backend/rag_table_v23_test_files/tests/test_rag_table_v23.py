"""RAG Table v2.3 regression: truthful diagnostics and structural heading recovery."""
from types import SimpleNamespace

import pymupdf

from app.services.rag_pdf_table_recovery import (
    _header_and_rows,
    _word_aligned_candidates,
    describe_pdf_tables,
    recover_text_aligned_tables,
)
from app.services.rag_table_extraction import extract_rag_table_records


def synthetic_pdf(rows=None):
    if rows is None:
        rows = [
            ("System", "HotpotQA (EM)", "2Wiki (EM)", "MuSiQue (EM)"),
            ("GraphRAG*", "0.556", "0.566", "0.310"),
            ("ThreadRAG*", "0.574", "0.560", "0.288"),
        ]
    with pymupdf.open() as doc:
        page = doc.new_page()
        for j, row in enumerate(rows):
            for i, val in enumerate(row):
                page.insert_text((42 + i * 150, 100 + j * 28), val, fontsize=10)
        return doc.tobytes()


def test_two_level_header_preserves_dataset_and_metric():
    matrix = [
        ["System", "HotpotQA", "", "2Wiki", ""],
        ["", "EM", "F1", "EM", "F1"],
        ["GraphRAG*", "0.556", "0.66", "0.566", "0.67"],
        ["ThreadRAG*", "0.574", "0.68", "0.56", "0.69"],
    ]
    found = _header_and_rows(matrix)
    assert found is not None
    headers, rows = found
    frag = SimpleNamespace(id="t", page=8, text="EXTRACTED TABLE (page 8)\nColumns: " + " | ".join(headers)
                           + "\n" + "\n".join("Row: " + " | ".join(row) for row in rows))
    result = extract_rag_table_records([frag])
    assert len(result.records) == 8
    assert {(r['dataset_name'], r['metric_name']) for r in result.records} == {
        ('HotpotQA', 'Exact Match'), ('HotpotQA', 'F1'),
        ('2Wiki', 'Exact Match'), ('2Wiki', 'F1'),
    }


def test_no_metric_in_header_or_caption_keeps_table_incomplete():
    header, rows = _header_and_rows([
        ['System', 'HotpotQA', '2Wiki'],
        ['GraphRAG*', '0.556', '0.566'],
        ['ThreadRAG*', '0.574', '0.560'],
    ])
    fragment = SimpleNamespace(id='t', page=8, text='EXTRACTED TABLE (page 8)\nColumns: '
                               + ' | '.join(header) + '\n' + '\n'.join(
                                   'Row: ' + ' | '.join(row) for row in rows))
    assert extract_rag_table_records([fragment]).records == []


def test_aligned_geometry_can_recover_without_pymupdf_find_tables(monkeypatch):
    pdf = synthetic_pdf()
    # Force native table detection to miss the entire grid.
    monkeypatch.setattr(pymupdf.Page, 'find_tables', lambda self, **kwargs: SimpleNamespace(tables=[]))
    recovered = recover_text_aligned_tables(pdf)
    assert recovered
    fragments = [SimpleNamespace(id=str(i), text=r.text, page=r.page) for i, r in enumerate(recovered)]
    rows = extract_rag_table_records(fragments).records
    assert len(rows) == 6
    assert {(r['rag_variant'], r['dataset_name']): r['metric_value'] for r in rows}[
        ('GraphRAG*', 'MuSiQue')] == 0.31


def test_geometric_scan_does_not_read_unheaded_numbers():
    with pymupdf.open() as doc:
        page = doc.new_page()
        for i, line in enumerate(['GraphRAG* HotpotQA 0.556', 'ThreadRAG* HotpotQA 0.574',
                                  'Another example: 0.310', 'Result 0.566']):
            page.insert_text((50, 85 + 26*i), line, fontsize=10)
        pdf = doc.tobytes()
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        assert _word_aligned_candidates(doc[0], 1) == []
    assert recover_text_aligned_tables(pdf) == []


def test_diagnostics_real_pdf_non_mutating():
    data = describe_pdf_tables(synthetic_pdf())
    assert data['pdf_readable'] is True and data['page_count'] == 1
    assert data['pages'][0]['words'] > 0
    assert data['pages'][0]['aligned_fragments'] > 0
    assert describe_pdf_tables(b'not pdf')['pdf_readable'] is False


def test_diagnostics_endpoint_distinguishes_missing_pdf(client):
    res = client.post('/api/v1/documents', data={'domain':'rag'}, files={
        'file': ('table.pdf', synthetic_pdf(), 'application/pdf')})
    assert res.status_code == 201
    pid = res.json()['id']
    response = client.get('/api/v1/scientific/rag/table-diagnostics', params={'publication_id': pid})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['source_pdf_present'] and body['source_pdf_readable']
    assert body['page_count'] == 1
    # Preview must also be able to extract the stronger geometric matrix.
    preview = client.get('/api/v1/scientific/rag/table-preview', params={'publication_id':pid}).json()
    assert preview['complete_context_count'] >= 6
    assert client.get(f'/api/v1/documents/{pid}').json()['fragment_count'] == res.json()['fragment_count']
    # Simulate lost backing PDF (DB remains unchanged).
    from app.config import Settings
    from pathlib import Path
    # TestClient supplies the configured active app via its internal app instance.
    source = client.app.state.settings.data_dir / 'uploads' / f'{pid}.pdf'
    source.unlink()
    missing = client.get('/api/v1/scientific/rag/table-diagnostics', params={'publication_id':pid}).json()
    assert missing['source_pdf_present'] is False
    assert 'source_pdf_missing' in missing['diagnosis']


def test_diagnostics_rejects_unknown_id(client):
    resp = client.get('/api/v1/scientific/rag/table-diagnostics', params={'publication_id':'missing'})
    assert resp.status_code == 404
