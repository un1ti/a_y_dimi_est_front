"""Adapt the real extraction DB records to the separately developed scientific module.

No LLM call or database mutation occurs here. Never invent missing experimental context.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.db.models import ResultRecord
from scientific_arbitrator import Evidence, SolarResult, RAGResult


SOLAR_METRICS = {
    "PCE": ("pce_pct", "%"),
    "VOC": ("voc_v", "V"),
    "JSC": ("jsc_ma_cm2", "mA/cm2"),
    "FF": ("ff_pct", "%"),
}


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Converted:
    result: SolarResult | RAGResult
    warnings: list[str]


def evidence_for(record: ResultRecord, *, field_names: set[str]) -> list[Evidence]:
    output = []
    for item in json.loads(record.evidence_json):
        if item.get("field") not in field_names or item.get("verification") != "quote_matched":
            continue
        output.append(Evidence(
            source_id=item["fragment_id"],
            page=item.get("page"),
            quote=item.get("quote"),
            extraction_method="llm_or_parser",
        ))
    return output


def _solar(record: ResultRecord, solar_metric: str) -> Converted:
    metric = solar_metric.upper()
    if metric not in SOLAR_METRICS:
        raise ConversionError("Solar metric must be one of: PCE, Voc, Jsc, FF")
    key, unit = SOLAR_METRICS[metric]
    data: dict[str, Any] = json.loads(record.data_json)
    val = data.get(key)
    if val is None:
        raise ConversionError(f"Field {key} is absent or not source-supported in this extracted record")

    # 'material_name' may mean NiO transport layer, NOT the absorber.
    # 'device_type' is not necessarily a standardized device architecture.
    # Missing scientific metadata remains None, not guessed.
    spectrum = data.get("spectrum")
    intensity = data.get("light_intensity_mw_cm2")
    conditions = f"{spectrum}; {intensity} mW/cm2" if spectrum and intensity is not None else None
    notes = []
    if conditions is None:
        notes.append("Measurement spectrum and/or intensity not fully established; not inferred")
    if data.get("material_name") and not data.get("material_class"):
        notes.append("material_name may describe a transport layer; absorber_material left unknown")
    return Converted(SolarResult(
        study_id=record.publication_id,
        device_id=data.get("device_label"),
        absorber_material=None,  # not supplied separately in current Finding schema
        architecture=data.get("architecture"),
        metric="Voc" if metric == "VOC" else "Jsc" if metric == "JSC" else metric,
        value=val,
        unit=unit,
        statistic=data.get("aggregation"),
        measurement_conditions=conditions,
        scan_direction=data.get("scan_direction"),
        active_area_cm2=data.get("active_area_cm2"),
        voc_v=data.get("voc_v") if evidence_for(record, field_names={"voc_v"}) else None,
        jsc_ma_cm2=data.get("jsc_ma_cm2") if evidence_for(record, field_names={"jsc_ma_cm2"}) else None,
        ff_pct=data.get("ff_pct") if evidence_for(record, field_names={"ff_pct"}) else None,
        light_intensity_mw_cm2=(data.get("light_intensity_mw_cm2")
            if evidence_for(record, field_names={"light_intensity_mw_cm2"}) else None),
        evidence=evidence_for(record, field_names={key, "voc_v", "jsc_ma_cm2", "ff_pct", "light_intensity_mw_cm2"}),
    ), notes)


def _rag(record: ResultRecord) -> Converted:
    data: dict[str, Any] = json.loads(record.data_json)
    metric_name = data.get("metric_name")
    metric_value = data.get("metric_value")
    if metric_name is None or metric_value is None:
        raise ConversionError("RAG extraction lacks source-supported metric_name or metric_value")
    unit = (data.get("metric_unit") or "").strip().lower()
    value = float(metric_value)
    notes: list[str] = []
    if unit in {"%", "percent", "percentage"}:
        value /= 100.0
        notes.append("Metric value converted from explicit percentage to fraction")
    elif unit in {"fraction", "ratio", "0-1", "", "score"}:
        if unit == "":
            notes.append("Metric unit not specified; no conversion applied")
    else:
        notes.append(f"Unrecognized metric unit {unit!r}; no conversion applied")

    # Explicit @k in the metric name is evidence for k when separate metric_k is absent.
    parsed_name = re.match(r"^\s*(.*?)\s*@\s*(\d+)\s*$", str(metric_name))
    k = data.get("metric_k")
    if parsed_name:
        metric_name = parsed_name.group(1)
        if k is None:
            k = int(parsed_name.group(2))
        elif int(k) != int(parsed_name.group(2)):
            raise ConversionError("Conflicting metric_k and @k in source-derived metric_name")
    # RAG_PROFILE_V21_DATASET_RECOVERY
    from scientific_arbitrator.rag_context_v21 import recover_dataset
    stored_evidence = json.loads(record.evidence_json)
    resolved_dataset, recovery_source = recover_dataset(data, stored_evidence)
    if recovery_source == "recovered_from_verified_metric_quote":
        notes.append("Dataset recovered provisionally from verified metric quote; table association not independently verified")
    return Converted(RAGResult(
        study_id=record.publication_id,
        system_id=(data.get("config_label") or (data.get("rag_variant") if evidence_for(record, field_names={"rag_variant"}) else None)),
        llm=data.get("generator_model"),
        embedding_model=data.get("embedding_model"),
        retriever=data.get("retriever_model") or data.get("retrieval_method"),
        reranker=data.get("reranker_model"),
        chunking_strategy=data.get("chunking_method"),
        metric=str(metric_name),
        value=value,
        k=k,
        dataset=resolved_dataset,
        evaluation_protocol=data.get("evaluation_protocol"),
        split=data.get("data_split"),
        evidence=evidence_for(record, field_names={"metric_value", "metric_name", "metric_k"}),
    ), notes)


def convert_record(record: ResultRecord, *, solar_metric: str = "PCE") -> Converted:
    if record.domain == "solar":
        return _solar(record, solar_metric)
    if record.domain == "rag":
        return _rag(record)
    raise ConversionError(f"Unsupported domain {record.domain!r}")
