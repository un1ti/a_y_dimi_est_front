from scientific_arbitrator.rag_context_v21 import recover_dataset
from scientific_arbitrator.rag_audit_v21 import audit_records
from scientific_arbitrator import RAGResult, arbitrate_rag, validate_rag, Verdict


def quote(q, field='metric_value', status='quote_matched'):
    return {'field': field, 'quote': q, 'verification': status, 'fragment_id': 'fragment-1'}


def record(**changes):
    data = dict(study_id='paper', metric='Exact Match', value=0.556, system_id='GraphRAG*',
                dataset='HotpotQA', evaluation_protocol='Exact Match test', split='test')
    data.update(changes)
    return RAGResult(**data)


def test_exact_match_never_requires_k():
    assert 'K_UNSPECIFIED' not in {i.code for i in validate_rag(record()).issues}


def test_recall_requires_k():
    assert 'K_UNSPECIFIED' in {i.code for i in validate_rag(record(metric='Recall', k=None)).issues}


def test_dataset_recovery_is_exact_and_grounded():
    found, how = recover_dataset({'metric_value': 0.556}, [quote('HotpotQA 0.556')])
    assert (found, how) == ('HotpotQA', 'recovered_from_verified_metric_quote')


def test_wrong_number_or_unverified_quote_is_rejected():
    assert recover_dataset({'metric_value': 0.556}, [quote('HotpotQA 0.5567')])[0] is None
    assert recover_dataset({'metric_value': 0.556}, [quote('HotpotQA 0.556', status='unverified')])[0] is None


def test_multiple_datasets_is_ambiguous():
    assert recover_dataset({'metric_value': 0.556}, [quote('HotpotQA 0.556 2Wiki 0.566')])[0] is None


def test_existing_dataset_not_overwritten():
    assert recover_dataset({'metric_value': 0.556, 'dataset_name': 'custom'},
                           [quote('HotpotQA 0.556')])[0] == 'custom'


def test_comparison_on_two_distinct_datasets_is_incomparable():
    v = arbitrate_rag(record(), record(dataset='2Wiki', value=0.566))
    assert v.verdict == Verdict.INCOMPARABLE
    assert 'dataset' in v.blocking_fields


def test_missing_protocol_is_insufficient():
    assert arbitrate_rag(record(), record(evaluation_protocol=None)).verdict == Verdict.INSUFFICIENT_DATA


def test_change_model_is_comparable():
    assert arbitrate_rag(record(retriever='BM25'), record(retriever='dense')).verdict == Verdict.COMPARABLE


def test_audit_reports_not_deletes_duplicates():
    data = {'metric_value': 0.556, 'metric_name': 'Exact Match', 'rag_variant':'GraphRAG*'}
    r = [{'id': 'a', 'data': data, 'evidence': [quote('HotpotQA 0.556')]},
         {'id': 'b', 'data': data, 'evidence': [quote('HotpotQA 0.556')]}]
    audit = audit_records(r)
    assert audit['total'] == 2
    assert audit['recovered_dataset_count'] == 2
    assert audit['potential_extra_rows'] == 1
    assert len(audit['records']) == 2
