"""Search only already extracted scientific records; never calls the LLM.

Designed for the SQLite hackathon MVP. One latest successful extraction run per
publication is included by default, preventing duplicate results after retries.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExtractionRun, Publication, ResultRecord
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/scientific", tags=["Scientific Search"])

SOLAR_METRICS = {
    "pce_pct": "%", "voc_v": "V", "jsc_ma_cm2": "mA/cm²",
    "ff_pct": "%", "active_area_cm2": "cm²", "bandgap_ev": "eV",
    "jsc_eqe_ma_cm2": "mA/cm²", "light_intensity_mw_cm2": "mW/cm²",
}
RAG_METRICS = {"metric_value": None, "latency_ms": "ms", "tokens_per_query": "tokens"}


class SearchResult(BaseModel):
    record_id: str
    publication_id: str
    publication_filename: str
    domain: Literal["solar", "rag"]
    label: str | None = None
    metric: str | None = None
    value: float | None = None
    unit: str | None = None
    data: dict
    evidence: list[dict]
    validation_status: str


class SearchResponse(BaseModel):
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    results: list[SearchResult]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_filter(domain: str, metric: str | None) -> tuple[str | None, str | None, int | None]:
    if not metric:
        return None, None, None
    if domain == "solar":
        key = metric.strip().lower()
        aliases = {"pce": "pce_pct", "voc": "voc_v", "jsc": "jsc_ma_cm2", "ff": "ff_pct"}
        key = aliases.get(key, key)
        if key not in SOLAR_METRICS:
            raise HTTPException(422, f"Unknown Solar metric: {metric}")
        return key, None, None
    if domain == "rag":
        key = metric.strip().lower()
        if key in {"latency_ms", "tokens_per_query"}:
            return key, None, None
        if key == "metric_value":
            return key, None, None
        match = re.fullmatch(r"(.+?)(?:@(\d+))?", metric.strip())
        if not match or not match.group(1).strip():
            raise HTTPException(422, "Invalid RAG metric name")
        return "metric_value", match.group(1).strip(), int(match.group(2)) if match.group(2) else None
    raise HTTPException(422, "Specify domain=solar or domain=rag when filtering by metric")


@router.get("/search", response_model=SearchResponse)
def search_scientific_results(
    domain: Literal["solar", "rag"] | None = None,
    q: str | None = Query(None, max_length=200),
    metric: str | None = Query(None, max_length=100),
    min_value: float | None = None,
    max_value: float | None = None,
    material: str | None = Query(None, max_length=150),
    dataset: str | None = Query(None, max_length=150),
    retrieval_method: str | None = Query(None, max_length=150),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Filter persisted findings by typed values and scientific metadata."""
    if min_value is not None and max_value is not None and min_value > max_value:
        raise HTTPException(422, "min_value cannot exceed max_value")
    if metric and not domain:
        raise HTTPException(422, "domain is required when metric is supplied")
    if (min_value is not None or max_value is not None) and not metric:
        raise HTTPException(422, "metric is required for numeric filtering")
    if material and domain != "solar":
        raise HTTPException(422, "material filter requires domain=solar")
    if (dataset or retrieval_method) and domain != "rag":
        raise HTTPException(422, "dataset/retrieval_method require domain=rag")

    field, metric_name, metric_k = _metric_filter(domain, metric) if domain else (None, None, None)
    # We only search records from the latest completed extraction of each publication,
    # not unsuccessful/in-progress attempts and not old reruns.
    runs = db.scalars(select(ExtractionRun).where(ExtractionRun.status == "done").order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())).all()
    current_run: dict[str, str] = {}
    for run in runs:
        current_run.setdefault(run.publication_id, run.id)
    if not current_run:
        return SearchResponse(total=0, offset=offset, limit=limit, results=[])
    stmt = select(ResultRecord, Publication).join(Publication, ResultRecord.publication_id == Publication.id).where(ResultRecord.run_id.in_(tuple(current_run.values())))
    if domain:
        stmt = stmt.where(ResultRecord.domain == domain)
    stmt = stmt.order_by(ResultRecord.created_at.desc(), ResultRecord.id.desc())
    matches: list[SearchResult] = []
    query = (q or "").strip().casefold()
    for record, publication in db.execute(stmt):
        data = json.loads(record.data_json)
        if material and material.casefold() not in " ".join(str(data.get(k) or "") for k in ("material_name", "material_class")).casefold():
            continue
        if dataset and dataset.casefold() not in str(data.get("dataset_name") or "").casefold():
            continue
        if retrieval_method and retrieval_method.casefold() not in str(data.get("retrieval_method") or "").casefold():
            continue
        if query and query not in (publication.filename + " " + " ".join(str(v) for v in data.values() if v is not None)).casefold():
            continue
        if metric_name is not None and metric_name.casefold() != str(data.get("metric_name") or "").casefold():
            continue
        if metric_k is not None and metric_k != data.get("metric_k"):
            continue
        value = _number(data.get(field)) if field else None
        if field and value is None:
            continue
        if min_value is not None and (value is None or value < min_value):
            continue
        if max_value is not None and (value is None or value > max_value):
            continue
        unit = (SOLAR_METRICS.get(field) if domain == "solar" else (data.get("metric_unit") if field == "metric_value" else RAG_METRICS.get(field))) if field else None
        label = (data.get("device_label") or data.get("device_type") if record.domain == "solar" else data.get("config_label") or data.get("rag_variant"))
        matches.append(SearchResult(
            record_id=record.id, publication_id=record.publication_id,
            publication_filename=publication.filename, domain=record.domain,
            label=label, metric=metric or field, value=value, unit=unit,
            data=data, evidence=json.loads(record.evidence_json),
            validation_status=record.validation_status,
        ))
    return SearchResponse(total=len(matches), offset=offset, limit=limit, results=matches[offset:offset + limit])
