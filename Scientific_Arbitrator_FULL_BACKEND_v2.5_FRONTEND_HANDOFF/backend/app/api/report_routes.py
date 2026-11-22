"""Export only the latest successful run as JSON or spreadsheet-safe CSV.

This is an extraction report, not a scientific certification.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.quality_routes import latest_records
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/scientific", tags=["Scientific Exports"])


def _safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Disable formula interpretation in Excel/LibreOffice/Google Sheets.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        text = "'" + text
    return text


@router.get("/reports/{publication_id}")
def export_report(publication_id: str,
                  format: Literal["json", "csv"] = Query("json"),
                  db: Session = Depends(get_db)):
    pub, records = latest_records(db, publication_id)
    rows = [{
        "record_id": r.id, "domain": r.domain,
        "data": json.loads(r.data_json), "evidence": json.loads(r.evidence_json),
        "validation_status": r.validation_status,
    } for r in records]
    if format == "json":
        return {
            "publication_id": pub.id, "filename": pub.filename,
            "domain": pub.domain, "total": len(rows), "results": rows,
            "note": "Extracted values with source traceability. Scientific validity not certified.",
        }
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(("record_id", "domain", "metric", "value", "system_or_device",
                     "dataset", "validation_status", "evidence_pages", "raw_data_json"))
    for row in rows:
        d = row["data"]
        metric = d.get("metric_name") if pub.domain == "rag" else "PCE"
        value = d.get("metric_value") if pub.domain == "rag" else d.get("pce_pct")
        system = (d.get("rag_variant") or d.get("config_label")) if pub.domain == "rag" else (d.get("device_label") or d.get("device_type"))
        pages = ",".join(str(p) for p in sorted({e.get("page") for e in row["evidence"] if isinstance(e.get("page"), int)}))
        values = (row["record_id"], row["domain"], metric, value, system,
                  d.get("dataset_name"), row["validation_status"], pages,
                  json.dumps(d, ensure_ascii=False))
        writer.writerow([_safe_csv_cell(v) for v in values])
    return Response(content="\ufeff" + content.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="arbitrator_{pub.id}.csv"',
                             "X-Content-Type-Options": "nosniff"})
