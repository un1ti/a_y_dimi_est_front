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
from app.services.rag_pdf_table_recovery import recover_text_aligned_tables, describe_pdf_tables
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


@router.get("/table-diagnostics")
def rag_table_diagnostics(
    publication_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Explain why preview is empty without exposing raw PDF text or using Qwen."""
    doc = db.get(Publication, publication_id)
    if doc is None or doc.domain != "rag":
        raise HTTPException(404, "RAG publication not found")
    fragments = db.scalars(select(SourceFragment).where(
        SourceFragment.publication_id == publication_id,
    )).all()
    saved_tables = sum(f.text.startswith("EXTRACTED TABLE (") for f in fragments)
    pdf_path = request.app.state.settings.data_dir / "uploads" / f"{publication_id}.pdf"
    result = {
        "publication_id": publication_id,
        "stored_fragment_count": len(fragments),
        "stored_table_fragment_count": saved_tables,
        "source_pdf_present": pdf_path.is_file(),
        "source_pdf_readable": None,
        "page_count": None,
        "pages": [],
    }
    if not pdf_path.is_file():
        result["diagnosis"] = "source_pdf_missing: original PDF is not in this backend's active DATA_DIR/uploads"
        return result
    diagnostic = describe_pdf_tables(
        pdf_path.read_bytes(), max_pages=request.app.state.settings.max_pdf_pages
    )
    result["source_pdf_readable"] = diagnostic.get("pdf_readable", False)
    result["page_count"] = diagnostic.get("page_count")
    result["pages"] = diagnostic.get("pages", [])
    if not diagnostic.get("pdf_readable"):
        result["diagnosis"] = "unreadable_pdf: " + str(diagnostic.get("reason", "unknown"))
    elif not any(p["words"] for p in result["pages"]):
        result["diagnosis"] = "no_text_layer: scanned pages may need OCR"
    elif any((p["line_tables"] or 0) + (p["text_tables"] or 0) + p["aligned_fragments"] > 0 for p in result["pages"]):
        result["diagnosis"] = "table_geometry_seen: no trustworthy complete mapping in current preview"
    else:
        result["diagnosis"] = "text_present_but_no_table_grid: inspect source page layout"
    return result
