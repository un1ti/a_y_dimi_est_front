"""RAG table v2.4 regression: deterministic three-axis PDF source mapping."""
from __future__ import annotations

from pathlib import Path
import os
from types import SimpleNamespace

import pymupdf

from app.schemas.domain import RagFinding
from app.services.grounding import ground_record
from app.services.rag_hierarchical_tables import recover_hierarchical_tables
from app.services.rag_pdf_table_recovery import describe_pdf_tables, recover_text_aligned_tables
from app.services.rag_table_extraction import extract_rag_table_records


def _table_pdf(*, incomplete: bool = False, figures_only: bool = False) -> bytes:
    """Tiny generated PDF simulating the physical 3-axis table, no real paper redistributed."""
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=841)
        def at(x, baseline, value, size=8):
            page.insert_text((x, baseline), value, fontsize=size)
        col_x = [124.0 + j*22 for j in range(18)]
        if not figures_only:
            at(77, 91, 'Methods')
            for j, name in enumerate(['ModelA-8B', 'ModelB-Plus', 'ModelC-mini']):
                at(157+j*132, 79, name)
            for j, ds in enumerate(['HotpotQA','2Wiki','MuSiQue']*3):
                at(col_x[2*j]+1, 94, ds, size=7)
            for j in range(18):
                at(col_x[j], 108, 'EM' if j%2==0 else 'F1', size=7)
            for i, method in enumerate(('GraphRAG*', 'ThreadRAG')):
                y = 138 + i*20
                at(77, y, method)
                for j in range(18):
                    if incomplete and i == 1 and j == 4:
                        continue
                    at(col_x[j], y, f'.{(240+3*j+i*20):03d}', size=7)
        else:
            for i, token in enumerate(('HotpotQA', 'EM', 'F1', '0.422', '0.513')):
                at(60+i*55, 145, token)
        return doc.tobytes()


def _parse_pdf(pdf: bytes):
    frags = recover_text_aligned_tables(pdf)
    parsed = extract_rag_table_records([
        SimpleNamespace(id=f'f{i}', page=frag.page, text=frag.text)
        for i, frag in enumerate(frags)
    ])
    return frags, parsed


def test_three_tier_geometry_generates_complete_grounded_rows():
    frags, parsed = _parse_pdf(_table_pdf())
    assert len(frags) == 2
    assert parsed.complete_context_count == 36
    assert {r['generator_model'] for r in parsed.records} == {'ModelA-8B', 'ModelB-Plus', 'ModelC-mini'}
    first = parsed.records[0]
    assert (first['rag_variant'], first['dataset_name'], first['metric_name']) == ('GraphRAG*', 'HotpotQA', 'Exact Match')
    assert first['metric_value'] == .240
    refs = {f'f{i}': SimpleNamespace(id=f'f{i}', page=frag.page, text=frag.text)
            for i, frag in enumerate(frags)}
    grounded, evidence, removed = ground_record(RagFinding.model_validate(first), refs)
    assert grounded['generator_model'] == 'ModelA-8B'
    assert grounded['metric_value'] == .240
    assert removed == [] and len(evidence) >= 5


def test_dropped_numeric_cell_discards_ambiguous_row():
    frags, parsed = _parse_pdf(_table_pdf(incomplete=True))
    assert len(frags) == 1
    assert parsed.complete_context_count == 18


def test_scattered_figure_labels_not_interpreted_as_table():
    frags, parsed = _parse_pdf(_table_pdf(figures_only=True))
    assert len(frags) == 0 and parsed.records == []


def test_diagnostics_reports_hierarchical_geometry():
    details = describe_pdf_tables(_table_pdf())
    assert details['pages'][0]['hierarchical_fragments'] == 2


def test_parser_not_truncated_at_200_and_keeps_final_method():
    fragment = 'EXTRACTED TABLE (page 6)\nColumns: Methods | HotpotQA (EM) [generator=ModelA-8B]'
    fragments = [SimpleNamespace(id=f'row-{i}', page=6, text=fragment+f'\nRow: System{i} | 0.5')
                 for i in range(252)]
    result = extract_rag_table_records(fragments)
    assert len(result.records) == 252
    assert result.records[-1]['rag_variant'] == 'System251'


def test_uploaded_d001_if_present_has_correct_multi_axis_values():
    # Optional local-source check, used in this build but does not require
    # redistribution of the copyrighted uploaded article inside the ZIP.
    source = Path(os.environ.get('RAG_V24_REAL_PDF', '/nonexistent/d001.pdf'))
    if not source.is_file():
        return
    frags, parsed = _parse_pdf(source.read_bytes())
    assert len(frags) == 14
    assert parsed.complete_context_count == 252
    assert all(f.page == 6 for f in frags)
    actual = {(r['rag_variant'],r['generator_model'],r['dataset_name'],r['metric_name']):r['metric_value']
              for r in parsed.records}
    assert actual[('ThreadRAG', 'Qwen3.5 plus', 'HotpotQA', 'Exact Match')] == .586
    assert actual[('ThreadRAG', 'GPT-4o mini', '2Wiki', 'F1')] == .663
    assert actual[('knowtrace', 'LLaMA3-8B-Instruct', 'HotpotQA', 'Exact Match')] == .396


def test_preview_api_exposes_model_context(client):
    response = client.post('/api/v1/documents', data={'domain': 'rag'},
        files={'file': ('multiaxis.pdf', _table_pdf(), 'application/pdf')})
    assert response.status_code == 201, response.text
    pid = response.json()['id']
    preview = client.get('/api/v1/scientific/rag/table-preview',
                         params={'publication_id':pid,'limit':100})
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data['complete_context_count'] == 36
    assert data['records'][0]['generator_model'] == 'ModelA-8B'
    assert data['records'][0]['source_page'] == 1
    diag = client.get('/api/v1/scientific/rag/table-diagnostics', params={'publication_id':pid})
    assert diag.status_code == 200
    assert 'hierarchical_table_recognized' in diag.json()['diagnosis']


def test_leading_decimal_quotes_are_numeric_but_not_the_integer_586():
    from app.services.grounding import numeric_supported
    assert numeric_supported('metric_value', .586, 'Row: ThreadRAG | .586 | .704')
    assert numeric_supported('metric_value', 0.5, 'Row: ThreadRAG | .500 | .600')
    assert not numeric_supported('metric_value', 586, 'Row: ThreadRAG | .586 | .704')
    assert not numeric_supported('metric_value', .586, 'Row: ThreadRAG | .585 | .704')


def test_uploaded_real_pdf_through_api_if_provided(client):
    source = Path(os.environ.get('RAG_V24_REAL_PDF', '/nonexistent/d001.pdf'))
    if not source.is_file():
        return
    response = client.post('/api/v1/documents', data={'domain': 'rag'},
        files={'file': ('D001.pdf', source.read_bytes(), 'application/pdf')})
    assert response.status_code == 201, response.text
    publication_id = response.json()['id']
    preview = client.get('/api/v1/scientific/rag/table-preview',
        params={'publication_id':publication_id,'limit':400})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body['complete_context_count'] == 252
    assert body['recovered_preview_fragments'] == 14
    assert all(item['source_page'] == 6 for item in body['records'])
    assert {(r['system'], r['dataset'], r['metric'], r['generator_model'], r['value'])
            for r in body['records']} >= {
                ('ThreadRAG', 'HotpotQA', 'Exact Match', 'Qwen3.5 plus', .586),
                ('ThreadRAG', 'HotpotQA', 'Exact Match', 'LLaMA3-8B-Instruct', .422),
            }
