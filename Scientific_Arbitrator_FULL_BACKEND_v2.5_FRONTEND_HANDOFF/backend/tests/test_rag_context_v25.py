"""Source-grounded experiment context and safety regression, using actual D001 if supplied."""
from pathlib import Path
import os

from .conftest import pdf_bytes
from app.services.rag_publication_context import publication_context

D001 = Path(os.environ.get('RAG_V24_REAL_PDF', '/mnt/data/D001.pdf'))


def test_context_missing_pdf_remains_unknown(tmp_path):
    c = publication_context(tmp_path/'no.pdf', 'p')
    assert c.split is None and c.evaluation_protocol is None and not c.evidence


def test_arbitrary_pdf_does_not_claim_shared_setup(tmp_path):
    p = tmp_path/'x.pdf'
    p.write_bytes(pdf_bytes('Same data splits in our evaluation.'))
    c = publication_context(p, 'p')
    assert c.split is None and not c.evidence


def test_real_pdf_exact_grounding_when_present():
    if not D001.exists():
        return
    c = publication_context(D001, 'real')
    assert c.evaluation_protocol and c.split
    assert not c.split_named
    assert len(c.evidence) == 2 and all(e.page == 6 for e in c.evidence)
    assert 'Trivedi et al.' in c.evidence[1].quote


def test_real_pdf_comparison_and_quality_e2e(client):
    if not D001.exists():
        return
    u = client.post('/api/v1/documents', data={'domain':'rag'},
                    files={'file':('D001.pdf', D001.read_bytes(), 'application/pdf')})
    assert u.status_code == 201, u.text
    pub = u.json()['id']
    a = client.post(f'/api/v1/documents/{pub}/analyze')
    assert a.status_code == 202
    recs = client.get(f'/api/v1/documents/{pub}/results').json()['records']
    assert len(recs) == 252
    def get(name, model):
        return next(r['id'] for r in recs if
                    r['data']['rag_variant']==name and
                    r['data']['generator_model']==model and
                    r['data']['dataset_name']=='HotpotQA' and
                    r['data']['metric_name']=='Exact Match')
    ra = get('RA-CoT', 'LLaMA3-8B-Instruct')
    thread = get('ThreadRAG','LLaMA3-8B-Instruct')
    res = client.post('/api/v1/scientific/compare', json={
        'left_record_id':ra,'right_record_id':thread})
    assert res.status_code == 200, res.text
    v=res.json()
    assert v['verdict']=='comparable', v
    assert v['blocking_fields']==[]
    assert v['experimental_context']['same_llm'] is True
    assert v['experimental_context']['shared_pdf_table_verified'] is True
    assert v['experimental_context']['left']['split_name_known'] is False
    assert len(v['experimental_context']['left']['source_evidence'])==2
    assert len(v['evidence']['left'])>=4
    val=client.get(f'/api/v1/scientific/results/{ra}/validate').json()
    assert val['normalized_record']['split']
    assert val['inherited_context']['split_name_known'] is False
    quality=client.get(f'/api/v1/scientific/quality/{pub}',params={'limit':300}).json()
    assert quality['ready_for_comparison_count']==252
    assert all(r['context_inherited'] for r in quality['records'])
    audit = client.get('/api/v1/scientific/rag/audit',params={'publication_id':pub}).json()
    assert audit['total']==252
    assert audit['contextual_table_records']==252
    assert audit['contextual_table_context_verified'] is True
    assert audit['records'][0]['ready_for_comparison'] is False  # raw DB audit
    # No hidden mutations of source records: context is evaluated on demand.
    again=client.get(f'/api/v1/documents/{pub}/results').json()['records']
    assert all(r['data']['evaluation_protocol'] is None and r['data']['data_split'] is None
               for r in again)


def test_missing_source_pdf_cannot_be_laundered_into_comparability(client):
    if not D001.exists():
        return
    up=client.post('/api/v1/documents',data={'domain':'rag'},
       files={'file':('D001.pdf',D001.read_bytes(),'application/pdf')})
    pid=up.json()['id']
    assert client.post(f'/api/v1/documents/{pid}/analyze').status_code==202
    rows=client.get(f'/api/v1/documents/{pid}/results').json()['records']
    ra=next(r['id'] for r in rows if r['data']['rag_variant']=='RA-CoT')
    th=next(r['id'] for r in rows if r['data']['rag_variant']=='ThreadRAG')
    settings=client.app.state.settings
    (settings.data_dir/'uploads'/f'{pid}.pdf').unlink()
    r=client.post('/api/v1/scientific/compare',json={'left_record_id':ra,'right_record_id':th})
    assert r.status_code==200
    assert r.json()['verdict']=='insufficient_data'
    assert set(r.json()['blocking_fields'])=={'evaluation_protocol','split'}
