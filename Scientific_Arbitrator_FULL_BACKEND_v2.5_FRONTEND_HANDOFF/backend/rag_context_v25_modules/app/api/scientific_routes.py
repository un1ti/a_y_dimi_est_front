"""Endpoints exposing developer #2's scientific validation and arbitrator.

Read-only: these endpoints do not mutate extraction records or validation_status.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import ResultRecord
from app.db.session import get_db
from app.scientific.adapter import ConversionError, convert_record
from app.services.rag_publication_context import context_for_record, publication_context
from scientific_arbitrator import arbitrate_solar, arbitrate_rag, validate_solar, validate_rag

router = APIRouter(prefix="/api/v1/scientific", tags=["Scientific Validation & Comparison"])


class CompareRecordsRequest(BaseModel):
    left_record_id: str
    right_record_id: str
    solar_metric: Literal["PCE", "Voc", "Jsc", "FF"] = "PCE"


def _record(db: Session, ident: str) -> ResultRecord:
    rec = db.get(ResultRecord, ident)
    if rec is None:
        raise HTTPException(404, f"Result record {ident!r} not found")
    return rec


def _convert(rec: ResultRecord, metric: str):
    try:
        return convert_record(rec, solar_metric=metric)
    except (ConversionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/results/{record_id}/validate")
def validate_record(
    record_id: str,
    request: Request,
    solar_metric: Literal["PCE", "Voc", "Jsc", "FF"] = Query("PCE"),
    db: Session = Depends(get_db),
):
    rec = _record(db, record_id)
    converted = _convert(rec, solar_metric)
    inherited = None
    if rec.domain == "rag":
        inherited = context_for_record(rec, request.app.state.settings)
        if inherited.evidence:
            converted.result.evaluation_protocol = converted.result.evaluation_protocol or inherited.evaluation_protocol
            converted.result.split = converted.result.split or inherited.split
            converted.result.evidence.extend(inherited.evidence)
    report = (validate_solar(converted.result) if rec.domain == "solar" else validate_rag(converted.result))
    return {
        "record_id": rec.id,
        "domain": rec.domain,
        "normalized_record": converted.result.model_dump(mode="json"),
        "validation": report.model_dump(mode="json"),
        "conversion_warnings": converted.warnings,
        "inherited_context": _context_info(inherited),
        "note": "Profile checks include conditional PCE consistency when source-backed irradiance and components exist; not a full scientific certification. Does not change validation_status.",
    }


def _context_info(context):
    if context is None:
        return None
    return {
        "evaluation_protocol": context.evaluation_protocol,
        "split_reference": context.split,
        "split_name_known": context.split_named,
        "source_evidence": [e.model_dump(mode="json") for e in context.evidence],
        "note": context.note,
    }


@router.post("/compare")
def compare_records(payload: CompareRecordsRequest, request: Request, db: Session = Depends(get_db)):
    a = _record(db, payload.left_record_id)
    b = _record(db, payload.right_record_id)
    if a.domain != b.domain:
        raise HTTPException(422, "Cannot directly compare results from two different domains")
    left = _convert(a, payload.solar_metric)
    right = _convert(b, payload.solar_metric)
    inherited_left = inherited_right = None
    same_source_table = False
    if a.domain == "rag" and a.publication_id == b.publication_id:
        shared = publication_context(request.app.state.settings.data_dir / "uploads" /
                                     f"{a.publication_id}.pdf", a.publication_id)
        inherited_left = context_for_record(a, request.app.state.settings, shared=shared)
        inherited_right = context_for_record(b, request.app.state.settings, shared=shared)
        # Source-grounded inheritance only within the SAME PDF/table.
        same_source_table = bool(inherited_left.evidence and inherited_right.evidence)
        if same_source_table:
            for converted, inherited in ((left, inherited_left), (right, inherited_right)):
                converted.result.evaluation_protocol = (converted.result.evaluation_protocol
                                                        or inherited.evaluation_protocol)
                converted.result.split = converted.result.split or inherited.split
                converted.result.evidence.extend(inherited.evidence)
    verdict = (
        arbitrate_solar(left.result, right.result)
        if a.domain == "solar"
        else arbitrate_rag(left.result, right.result)
    )
    return {
        "left_record_id": a.id,
        "right_record_id": b.id,
        "metric": left.result.metric,
        "verdict": verdict.verdict.value,
        "domain": a.domain,
        "reasons": verdict.reasons,
        "blocking_fields": verdict.blocking_fields,
        "compared_fields": verdict.compared_fields,
        "evidence": {
            "left": [item.model_dump(mode="json") for item in left.result.evidence],
            "right": [item.model_dump(mode="json") for item in right.result.evidence],
        },
        "conversion_warnings": {"left": left.warnings, "right": right.warnings},
        "experimental_context": {
            "shared_pdf_table_verified": same_source_table,
            "left": _context_info(inherited_left),
            "right": _context_info(inherited_right),
            "llm_left": getattr(left.result, "llm", None),
            "llm_right": getattr(right.result, "llm", None),
            "same_llm": (left.result.llm == right.result.llm) if a.domain == "rag" else None,
        } if a.domain == "rag" else None,
        "note": "Prototype rules only. A positive comparability decision is not a complete scientific equivalence check.",
    }
