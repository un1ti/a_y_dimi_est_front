from scientific_arbitrator import arbitrate, Verdict


def solar(**overrides):
    data = dict(
        study_id="S1", metric="PCE", value=20.0, unit="%",
        statistic="mean", absorber_material="perovskite",
        architecture="n-i-p", measurement_conditions="AM1.5G",
        scan_direction="reverse", active_area_cm2=0.1,
    )
    data.update(overrides)
    return data


def rag(**overrides):
    data = dict(
        study_id="R1", metric="Recall", value=0.82, k=5,
        dataset="Dataset-A", evaluation_protocol="fixed test set",
        split="test", retriever="BM25", reranker="none",
        chunking_strategy="512-token", llm="Model-A",
        embedding_model="Embed-A",
    )
    data.update(overrides)
    return data


def test_solar_best_vs_mean_is_incomparable():
    result = arbitrate("solar", solar(statistic="best"), solar(study_id="S2", statistic="mean"))
    assert result.verdict == Verdict.INCOMPARABLE
    assert "statistic" in result.blocking_fields


def test_solar_missing_context_is_insufficient():
    a = solar(measurement_conditions=None)
    b = solar(study_id="S2", measurement_conditions=None)
    result = arbitrate("solar", a, b)
    assert result.verdict == Verdict.INSUFFICIENT_DATA


def test_solar_matching_context_comparable():
    result = arbitrate("solar", solar(), solar(study_id="S2", value=19.8))
    assert result.verdict == Verdict.COMPARABLE


def test_rag_recall_at_5_vs_recall_at_10_is_incomparable():
    result = arbitrate("rag", rag(k=5), rag(study_id="R2", value=0.91, k=10))
    assert result.verdict == Verdict.INCOMPARABLE
    assert "k" in result.blocking_fields


def test_rag_missing_dataset_is_insufficient():
    result = arbitrate(
        "rag",
        rag(dataset=None),
        rag(study_id="R2", dataset=None),
    )
    assert result.verdict == Verdict.INSUFFICIENT_DATA


def test_rag_matching_context_comparable():
    result = arbitrate("rag", rag(), rag(study_id="R2", value=0.91))
    assert result.verdict == Verdict.COMPARABLE


def test_metric_mismatch_is_incomparable():
    result = arbitrate("rag", rag(metric="Recall"), rag(study_id="R2", metric="MRR"))
    assert result.verdict == Verdict.INCOMPARABLE
