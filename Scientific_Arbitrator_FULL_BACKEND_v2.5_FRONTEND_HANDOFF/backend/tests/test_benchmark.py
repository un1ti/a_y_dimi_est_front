from scripts.benchmark_real_papers import rag_check, solar_check


def test_solar_benchmark_requires_all_four_metrics_from_same_record():
    record = {"data": {"pce_pct": 21.50, "voc_v": 1.193, "jsc_ma_cm2": 22.59, "ff_pct": 79.80}, "evidence": [{"field": "pce_pct"}]}
    checks = solar_check([record])
    assert checks["modified_same_record"] is True
    assert checks["control_same_record"] is False


def test_rag_benchmark_requires_variant_dataset_and_metric():
    record = {"data": {"rag_variant": "RAG-Seq.", "dataset_name": "NQ", "metric_name": "Exact Match", "metric_value": 44.5}, "evidence": [{"field": "metric_value"}]}
    checks = rag_check([record])
    assert checks["RAG-sequence_NQ_EM"] is True
    assert checks["RAG-token_NQ_EM"] is False
