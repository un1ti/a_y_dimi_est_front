"""Scientific search API contract tests, no Ollama required."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db.models import ExtractionRun, Publication, ResultRecord


def insert(client, domain, data, *, pubid=None, when=None, status='done'):
    pubid = pubid or str(uuid4())
    with client.app.state.sessionmaker() as session:
        if session.get(Publication, pubid) is None:
            session.add(Publication(id=pubid, filename=f'paper_{domain}.pdf', sha256=str(uuid4()), domain=domain, stored_path=f'uploads/{pubid}.pdf', page_count=2, fragment_count=1))
        runid = str(uuid4())
        session.add(ExtractionRun(id=runid, publication_id=pubid, status=status, llm_mode='mock', llm_model='test', created_at=when or datetime.now(timezone.utc)))
        recid = str(uuid4())
        session.add(ResultRecord(id=recid, run_id=runid, publication_id=pubid, domain=domain, data_json=json.dumps(data), evidence_json=json.dumps([{'field':'pce_pct', 'page':2, 'quote':'21.4'}]), validation_status='not_run'))
        session.commit()
    return recid, pubid


def test_solar_numeric_and_text(client):
    a, _ = insert(client, 'solar', {'material_name':'Perovskite', 'pce_pct':21.4, 'device_type':'Solar A'})
    insert(client, 'solar', {'material_name':'CIGS', 'pce_pct':15.3})
    result = client.get('/api/v1/scientific/search', params={'domain':'solar','metric':'PCE','min_value':20,'material':'perov'})
    assert result.status_code == 200, result.text
    assert result.json()['total'] == 1
    assert result.json()['results'][0]['record_id'] == a
    assert result.json()['results'][0]['value'] == 21.4
    assert result.json()['results'][0]['evidence'][0]['page'] == 2
    assert client.get('/api/v1/scientific/search', params={'domain':'solar','q':'SOLAR A'}).json()['total'] == 1


def test_rag_metric_k(client):
    a, _ = insert(client, 'rag', {'config_label':'Hybrid', 'retrieval_method':'BM25 + dense', 'metric_name':'Recall','metric_k':5,'metric_value':0.82,'metric_unit':'fraction','dataset_name':'NQ'})
    insert(client, 'rag', {'metric_name':'Recall','metric_k':10,'metric_value':0.95,'dataset_name':'NQ'})
    res = client.get('/api/v1/scientific/search', params={'domain':'rag', 'metric':'Recall@5','min_value':0.8, 'retrieval_method':'bm25','dataset':'nq'})
    assert res.status_code == 200, res.text
    assert res.json()['total']==1
    assert res.json()['results'][0]['record_id']==a


def test_null_not_zero(client):
    insert(client, 'solar', {'pce_pct':None})
    assert client.get('/api/v1/scientific/search',params={'domain':'solar','metric':'pce_pct','min_value':0}).json()['total']==0


def test_latest_completed_only(client):
    base = datetime(2026, 11, 20, tzinfo=timezone.utc)
    _, pubid = insert(client, 'solar', {'pce_pct':10}, when=base)
    b,_ = insert(client, 'solar', {'pce_pct':22}, pubid=pubid, when=base+timedelta(minutes=1))
    insert(client, 'solar', {'pce_pct':30}, pubid=pubid, when=base+timedelta(minutes=2), status='failed')
    res = client.get('/api/v1/scientific/search',params={'domain':'solar','metric':'PCE'})
    assert res.json()['total']==1
    assert res.json()['results'][0]['record_id']==b


def test_validation_and_pagination(client):
    for x in [10, 20, 30]: insert(client,'solar',{'pce_pct':x})
    response=client.get('/api/v1/scientific/search',params={'domain':'solar','metric':'PCE','limit':1,'offset':1})
    assert response.status_code==200
    assert response.json()['total']==3
    assert len(response.json()['results'])==1
    bad=[{'min_value':1}, {'domain':'solar','metric':'unknown'}, {'domain':'solar','metric':'PCE','min_value':30,'max_value':20}, {'domain':'rag','material':'x'}, {'domain':'solar','dataset':'NQ'}]
    for params in bad:
        assert client.get('/api/v1/scientific/search',params=params).status_code==422,params
