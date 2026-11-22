"""Read-only quality summary for the latest successful extraction run.

`ready_for_comparison` is conservative: it is NOT a scientific correctness claim.
"""
from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExtractionRun, Publication, ResultRecord
from app.db.session import get_db
from app.scientific.adapter import ConversionError, convert_record
from app.services.rag_publication_context import context_for_record, publication_context
from scientific_arbitrator import validate_rag, validate_solar

router = APIRouter(prefix="/api/v1/scientific", tags=["Scientific Quality"])


def latest_records(db: Session, publication_id: str) -> tuple[Publication, list[ResultRecord]]:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(404, "Publication not found")
    latest = db.scalar(select(ExtractionRun).where(
        ExtractionRun.publication_id == publication_id, ExtractionRun.status == "done"
    ).order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc()))
    if latest is None:
        return publication, []
    records = db.scalars(select(ResultRecord).where(ResultRecord.run_id == latest.id)
                         .order_by(ResultRecord.created_at, ResultRecord.id)).all()
    return publication, records


@router.get("/quality/{publication_id}")
def quality_report(publication_id: str, request: Request,
                   limit: int = Query(default=500, ge=1, le=1000),
                   db: Session = Depends(get_db)):
    pub, records = latest_records(db, publication_id)
    rows = []
    shared_context = (publication_context(request.app.state.settings.data_dir / "uploads" /
                                          f"{publication_id}.pdf", publication_id)
                      if pub.domain == "rag" else None)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for rec in records[:limit]:
        inherited = None
        data = json.loads(rec.data_json)
        evidence = json.loads(rec.evidence_json)
        try:
            converted = convert_record(rec)
            inherited = context_for_record(rec, request.app.state.settings, shared=shared_context) if pub.domain == "rag" else None
            if inherited and inherited.evidence:
                converted.result.evaluation_protocol = (converted.result.evaluation_protocol
                                                        or inherited.evaluation_protocol)
                converted.result.split = converted.result.split or inherited.split
                converted.result.evidence.extend(inherited.evidence)
            report = validate_solar(converted.result) if pub.domain == "solar" else validate_rag(converted.result)
            issue_codes = [issue.code for issue in report.issues]
            value = converted.result.value
            metric = converted.result.metric
            system = getattr(converted.result, "system_id", None) or getattr(converted.result, "device_id", None)
            dataset = getattr(converted.result, "dataset", None)
            ready = report.valid and bool(evidence) and not any(x in issue_codes for x in (
                "DATASET_UNSPECIFIED", "PROTOCOL_UNSPECIFIED", "SPLIT_UNSPECIFIED",
                "STATISTIC_UNSPECIFIED", "MEASUREMENT_CONTEXT_MISSING", "MATERIAL_UNSPECIFIED",
                "ACTIVE_AREA_UNSPECIFIED", "SCAN_DIRECTION_UNSPECIFIED", "PCE_FORMULA_NOT_CHECKED",
                "SYSTEM_UNSPECIFIED", "K_UNSPECIFIED", "EVIDENCE_MISSING",
            ))
            if pub.domain == "rag":
                ready = ready and bool(system)
            if pub.domain == "solar":
                ready = ready and converted.result.light_intensity_mw_cm2 is not None
            warnings = converted.warnings
        except (ConversionError, ValueError) as exc:
            issue_codes = ["CONVERSION_FAILED"]
            warnings = [str(exc)]
            value = None
            metric = None
            system = None
            dataset = None
            ready = False
        rows.append({
            "record_id": rec.id, "metric": metric, "value": value,
            "system_or_device": system, "dataset": dataset,
            "evidence_count": len(evidence), "ready_for_comparison": ready,
            "issues": issue_codes, "warnings": warnings,
            "context_inherited": bool(inherited and inherited.evidence),
        })
        # Possible duplicates only; missing context means identity cannot be verified.
        key = (pub.domain, system, dataset, metric, value)
        if metric is not None and value is not None:
            groups[key].append(rec.id)
    possible = [ids for ids in groups.values() if len(ids) > 1]
    return {
        "publication_id": publication_id, "domain": pub.domain,
        "total": len(records), "examined": len(rows), "truncated": len(rows) < len(records),
        "ready_for_comparison_count": sum(x["ready_for_comparison"] for x in rows),
        "potential_duplicate_groups": possible,
        "potential_extra_rows": sum(len(group) - 1 for group in possible),
        "records": rows,
        "note": "Read-only prototype quality assessment; duplicates are NOT deleted, missing values are not inferred, and readiness does not prove experimental equivalence.",
    }
