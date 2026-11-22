"""Read-only preview of structured RAG table extraction; no LLM requests or writes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Publication, SourceFragment
from app.db.session import get_db
from app.services.grounding import ground_record
from app.schemas.domain import RagFinding
from app.services.rag_table_extraction import extract_rag_table_records
from app.services.rag_pdf_table_recovery import recover_text_aligned_tables
from types import SimpleNamespace

router = APIRouter(prefix="/api/v1/scientific/rag", tags=["RAG Table Extraction v2.2"])


@router.get("/table-preview")
def rag_table_preview(
    publication_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    doc = db.get(Publication, publication_id)
    if doc is None or doc.domain != "rag":
        raise HTTPException(404, "RAG publication not found")
    fragments = db.scalars(select(SourceFragment).where(
        SourceFragment.publication_id == publication_id,
    ).order_by(SourceFragment.page, SourceFragment.position)).all()
    parsed = extract_rag_table_records(fragments, limit=limit)
    recovered_previews = 0
    if not parsed.records:
        # Ephemeral preview fragments are never added to SQLite.
        # The database record retains a generated safe filename within DATA_DIR.
        pdf_path = request.app.state.settings.data_dir / "uploads" / f"{publication_id}.pdf"
        if pdf_path.is_file():
            recovered = recover_text_aligned_tables(pdf_path.read_bytes(), limit=limit)
            recovered_previews = len(recovered)
            fragments = [SimpleNamespace(id=f"preview-{publication_id}-{i}",
                                         publication_id=publication_id, page=f.page,
                                         position=10000+i, text=f.text)
                         for i, f in enumerate(recovered)]
            parsed = extract_rag_table_records(fragments, limit=limit)
    references = {f.id: f for f in fragments}
    rows = []
    for item in parsed.records:
        data, evid, removed = ground_record(RagFinding.model_validate(item), references)
        if removed or len(evid) < 4:
            continue
        rows.append({
            "system": data["rag_variant"], "dataset": data["dataset_name"],
            "metric": data["metric_name"], "value": data["metric_value"],
            "metric_k": data.get("metric_k"),
            "source_page": references[evid[0]["fragment_id"]].page,
            "fragment_id": evid[0]["fragment_id"],
            "evidence": evid,
        })
    return {
        "publication_id": publication_id,
        "table_fragment_count": parsed.table_fragment_count,
        "recovered_preview_fragments": recovered_previews,
        "candidate_count": len(parsed.records),
        "complete_context_count": len(rows),
        "skipped_cells_or_rows": parsed.skipped_rows,
        "records": rows,
        "note": "Preview only. Exact row-to-column mapping required; no values inferred from free text. Does not modify existing extraction runs or certify experiments.",
    }
