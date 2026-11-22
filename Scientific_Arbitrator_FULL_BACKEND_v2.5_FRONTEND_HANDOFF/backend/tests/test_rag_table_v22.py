"""Regression coverage for provenance-preserving RAG table extraction v2.2."""
from types import SimpleNamespace

import pymupdf

from app.schemas.domain import RagFinding
from app.services.grounding import ground_record
from app.services.rag_table_extraction import extract_rag_table_records
from app.services.rag_pdf_table_recovery import recover_text_aligned_tables


def fragment(text: str, ident: str = "frag-1", page: int = 8):
    return SimpleNamespace(text=text, id=ident, page=page, position=1)


def test_horizontal_matrix_keeps_row_column_and_metric_association():
    src = fragment('''EXTRACTED TABLE (page 8)
Columns: System | HotpotQA (Exact Match) | 2Wiki (Exact Match) | MuSiQue (Exact Match)
Row: GraphRAG* | 0.556 | 0.566 | 0.310
Row: ThreadRAG* | 0.574 | 0.560 | 0.288''')
    parsed = extract_rag_table_records([src])
    assert parsed.table_fragment_count == 1
    assert parsed.complete_context_count == 6
    pairs = {(r['rag_variant'], r['dataset_name']): r['metric_value'] for r in parsed.records}
    assert pairs == {
        ('GraphRAG*', 'HotpotQA'): 0.556,
        ('GraphRAG*', '2Wiki'): 0.566,
        ('GraphRAG*', 'MuSiQue'): 0.310,
        ('ThreadRAG*', 'HotpotQA'): 0.574,
        ('ThreadRAG*', '2Wiki'): 0.56,
        ('ThreadRAG*', 'MuSiQue'): 0.288,
    }
    for raw in parsed.records:
        grounded, evidence, removed = ground_record(RagFinding.model_validate(raw), {src.id: src})
        assert not removed
        assert len(evidence) == 4
        assert grounded['metric_name'] == 'Exact Match'
        assert grounded['dataset_name'] and grounded['rag_variant']
        assert all(e['verification'] == 'quote_matched' for e in evidence)


def test_normal_form_system_dataset_metric_columns():
    src = fragment('''EXTRACTED TABLE (page 2)
Columns: Method | Dataset | Exact Match | F1
Row: GraphRAG | HotpotQA | 0.556 | 0.661
Row: GraphRAG | 2Wiki | 0.566 | 0.671''')
    parsed = extract_rag_table_records([src])
    assert len(parsed.records) == 4
    assert {(x['dataset_name'], x['metric_name'], x['metric_value']) for x in parsed.records} == {
        ('HotpotQA', 'Exact Match', 0.556), ('HotpotQA', 'F1', 0.661),
        ('2Wiki', 'Exact Match', 0.566), ('2Wiki', 'F1', 0.671),
    }


def test_transposed_system_columns():
    src = fragment('''EXTRACTED TABLE (page 4)
Columns: Dataset | GraphRAG (Exact Match) | ThreadRAG (Exact Match)
Row: HotpotQA | 0.556 | 0.574''')
    got = extract_rag_table_records([src]).records
    assert [(x['rag_variant'], x['dataset_name'], x['metric_value']) for x in got] == [
        ('GraphRAG', 'HotpotQA', 0.556), ('ThreadRAG', 'HotpotQA', 0.574)]


def test_no_metric_is_not_silently_invented():
    src = fragment('''EXTRACTED TABLE (page 8)
Columns: System | HotpotQA | 2Wiki
Row: GraphRAG | 0.556 | 0.566''')
    assert not extract_rag_table_records([src]).records


def test_plain_text_or_invalid_grid_cannot_create_records():
    sources = [fragment('GraphRAG HotpotQA EM 0.556'),
               fragment('''EXTRACTED TABLE (page 8)
Columns: System | HotpotQA (EM) | 2Wiki (EM)
Row: GraphRAG | 0.556''', 'frag-2')]
    assert not extract_rag_table_records(sources).records


def test_recall_k_and_percent_are_source_bounded():
    src = fragment('''EXTRACTED TABLE (page 6)
Columns: Model | HotpotQA Recall@5 (%)
Row: GraphRAG | 82.4%''')
    got = extract_rag_table_records([src]).records
    assert len(got) == 1
    assert got[0]['metric_name'] == 'Recall'
    assert got[0]['metric_k'] == 5
    assert got[0]['metric_unit'] == 'percent'
    grounded, evidence, removed = ground_record(RagFinding.model_validate(got[0]), {src.id: src})
    assert not removed and len(evidence) == 6
    assert grounded['metric_value'] == 82.4


def _borderless_pdf():
    with pymupdf.open() as doc:
        page = doc.new_page()
        rows = [
            ('System', 'HotpotQA (EM)', '2Wiki (EM)', 'MuSiQue (EM)'),
            ('GraphRAG*', '0.556', '0.566', '0.310'),
            ('ThreadRAG*', '0.574', '0.560', '0.288'),
        ]
        xs = (42, 195, 335, 460)
        for j, row in enumerate(rows):
            for i, val in enumerate(row):
                page.insert_text((xs[i], 100 + j * 28), val, fontsize=10)
        return doc.tobytes()


def test_recovers_borderless_pdf_with_independent_cell_positions():
    extracted = recover_text_aligned_tables(_borderless_pdf())
    assert extracted, 'Borderless RAG grid should be detected by PyMuPDF text strategy'
    sample = [fragment(f.text, ident=f'table-{i}', page=f.page) for i, f in enumerate(extracted)]
    got = extract_rag_table_records(sample).records
    assert any(x['rag_variant'] == 'GraphRAG*' and x['dataset_name'] == 'HotpotQA'
               and x['metric_value'] == 0.556 for x in got)


def test_integration_preview_rerun_and_latest_audit(client):
    pdf = _borderless_pdf()
    response = client.post('/api/v1/documents',
                           data={'domain': 'rag'},
                           files={'file': ('borderless.pdf', pdf, 'application/pdf')})
    assert response.status_code == 201, response.text
    pid = response.json()['id']
    initial_count = response.json()['fragment_count']
    preview = client.get('/api/v1/scientific/rag/table-preview', params={'publication_id': pid})
    assert preview.status_code == 200, preview.text
    assert preview.json()['complete_context_count'] >= 3
    # Preview must not add source fragments or extraction runs.
    assert client.get(f'/api/v1/documents/{pid}').json()['fragment_count'] == initial_count
    assert client.get(f'/api/v1/documents/{pid}/results').json()['records'] == []
    first = client.post(f'/api/v1/documents/{pid}/analyze')
    assert first.status_code == 202, first.text
    first_job = client.get(f"/api/v1/jobs/{first.json()['id']}").json()
    assert first_job['status'] == 'done'
    assert first_job['llm_mode'] == 'table'
    assert first_job['llm_model'] == 'deterministic-pdf-table-v2.2'
    results = client.get(f'/api/v1/documents/{pid}/results').json()['records']
    assert len(results) >= 3
    assert all(r['data']['dataset_name'] and r['data']['rag_variant'] and
               r['data']['metric_name'] and r['data']['metric_value'] is not None for r in results)
    assert all(len(r['evidence']) >= 4 for r in results)
    # Search works on real persisted dataset_name, not provisional recovery.
    search = client.get('/api/v1/scientific/search', params={'domain': 'rag', 'dataset': 'HotpotQA'})
    assert search.status_code == 200, search.text
    assert any(r['data']['dataset_name'] == 'HotpotQA' for r in search.json()['results'])
    second = client.post(f'/api/v1/documents/{pid}/analyze')
    assert client.get(f"/api/v1/jobs/{second.json()['id']}").json()['status'] == 'done'
    current = client.get('/api/v1/scientific/rag/audit', params={'publication_id': pid}).json()
    history = client.get('/api/v1/scientific/rag/audit', params={'publication_id': pid, 'scope': 'all'}).json()
    assert current['scope'] == 'latest'
    assert current['total'] == len(results)
    assert history['total'] == 2 * len(results)
    assert current['missing_dataset_after_recovery'] == 0
    assert current['missing_system'] == 0
    # Still missing evaluation_protocol and data_split, cannot claim comparability.
    assert not any(r['ready_for_comparison'] for r in current['records'])


def test_explicit_nearby_caption_can_supply_metric_for_dataset_columns():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 53), 'Table 1: Exact Match scores on three benchmarks', fontsize=10)
        grid = [('System', 'HotpotQA', '2Wiki'),
                ('GraphRAG', '0.556', '0.566'),
                ('ThreadRAG', '0.574', '0.560')]
        for i, row in enumerate(grid):
            for j, value in enumerate(row):
                page.insert_text((42 + j * 160, 101 + i * 27), value, fontsize=10)
        detected = recover_text_aligned_tables(document.tobytes())
    assert detected, 'An explicit nearby metric caption can anchor an otherwise ambiguous grid'
    rows = extract_rag_table_records([fragment(x.text, str(i)) for i, x in enumerate(detected)]).records
    assert any(row['dataset_name'] == 'HotpotQA' and row['metric_name'] == 'Exact Match'
               for row in rows)
