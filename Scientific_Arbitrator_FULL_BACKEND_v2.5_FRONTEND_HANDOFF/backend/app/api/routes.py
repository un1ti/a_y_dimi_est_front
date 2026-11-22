from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExtractionRun, Publication, ResultRecord, SourceFragment
from app.db.session import get_db
from app.schemas.api import DocumentOut, DomainInfo, EvidenceOut, FragmentOut, JobOut, RecordOut, ResultsOut
from app.schemas.domain import Domain
from app.services.analysis import run_extraction
from app.services.pdf_parser import PDFParseError, parse_pdf

router = APIRouter(prefix="/api/v1")


def _document_out(doc: Publication, *, created: bool = False) -> DocumentOut:
    return DocumentOut(
        id=doc.id, filename=doc.filename, sha256=doc.sha256, domain=doc.domain,
        page_count=doc.page_count, fragment_count=doc.fragment_count,
        text_status=doc.text_status, created_at=doc.created_at, created=created,
    )


def _job_out(job: ExtractionRun) -> JobOut:
    return JobOut(
        id=job.id, publication_id=job.publication_id, status=job.status,
        llm_mode=job.llm_mode, llm_model=job.llm_model,
        error=job.error, created_at=job.created_at, finished_at=job.finished_at,
        record_count=len(job.records),
    )


def _record_out(record: ResultRecord) -> RecordOut:
    return RecordOut(
        id=record.id, run_id=record.run_id, publication_id=record.publication_id,
        domain=record.domain, data=json.loads(record.data_json),
        evidence=[EvidenceOut.model_validate(x) for x in json.loads(record.evidence_json)],
        validation_status=record.validation_status, created_at=record.created_at,
    )


def _get_or_404(db: Session, model, ident: str, name: str):
    entity = db.get(model, ident)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return entity


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "the-scientific-arbitrator"}


@router.get("/llm/status")
def llm_status(request: Request) -> dict[str, object]:
    """Non-secret configuration diagnostics. Configured does not mean reachable."""
    settings = request.app.state.settings
    from urllib.parse import urlparse
    host = urlparse(settings.llm_base_url).hostname or ""
    configured = (
        settings.llm_mode == "openai"
        and settings.llm_model not in {"local-model", "your-model-name", "YOUR_MODEL"}
        and (bool(settings.llm_api_key) or host in {"127.0.0.1", "localhost", "::1"})
    )
    return {"mode": settings.llm_mode, "model": "regex-demo" if settings.llm_mode == "mock" else settings.llm_model, "configured": configured, "connected": None}


@router.get("/domains", response_model=list[DomainInfo])
def domains() -> list[DomainInfo]:
    return [
        DomainInfo(code="solar", label="Тонкоплёночные солнечные элементы", description="Materials, devices, measurements, photoelectric metrics"),
        DomainInfo(code="rag", label="RAG-системы", description="Retrieval configurations, evaluation datasets, experiments and metrics"),
    ]


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(request: Request, response: Response, file: UploadFile = File(...), domain: Domain = Form(...), db: Session = Depends(get_db)) -> DocumentOut:
    max_bytes = request.app.state.settings.max_upload_mb * 1024 * 1024
    try:
        data = await file.read(max_bytes + 1)
    finally:
        await file.close()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds {request.app.state.settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(status_code=422, detail="Empty upload")
    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Publication).where(Publication.sha256 == sha256, Publication.domain == domain))
    if existing:
        response.status_code = status.HTTP_200_OK
        return _document_out(existing, created=False)
    try:
        parsed = parse_pdf(data, request.app.state.settings.max_pdf_pages)
    except PDFParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    publication_id = str(uuid4())
    # Never trust the uploaded filename as a filesystem path.
    raw_name = (file.filename or "upload.pdf").replace("\\", "/").split("/")[-1]
    safe_name = raw_name[:255] or "upload.pdf"
    path: Path = request.app.state.settings.data_dir / "uploads" / f"{publication_id}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        document = Publication(
            id=publication_id, filename=safe_name, sha256=sha256,
            domain=domain, stored_path=f"uploads/{publication_id}.pdf", page_count=parsed.page_count,
            fragment_count=len(parsed.fragments), text_status=parsed.text_status,
        )
        db.add(document)
        for chunk in parsed.fragments:
            db.add(SourceFragment(
                id=str(uuid4()), publication_id=publication_id,
                page=chunk.page, position=chunk.position, text=chunk.text,
            ))
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return _document_out(document, created=True)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(domain: Domain | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    stmt = select(Publication).order_by(Publication.created_at.desc()).limit(limit)
    if domain:
        stmt = stmt.where(Publication.domain == domain)
    return [_document_out(x) for x in db.scalars(stmt)]


@router.get("/documents/{publication_id}", response_model=DocumentOut)
def get_document(publication_id: str, db: Session = Depends(get_db)):
    return _document_out(_get_or_404(db, Publication, publication_id, "Publication"))


@router.get("/documents/{publication_id}/file")
def get_document_file(publication_id: str, request: Request, db: Session = Depends(get_db)):
    doc = _get_or_404(db, Publication, publication_id, "Publication")
    # Resolve from the active data directory, including after moving .data
    # from macOS to Windows. Existing absolute stored_path values are ignored.
    path = request.app.state.settings.data_dir / "uploads" / f"{doc.id}.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename, content_disposition_type="inline")


@router.get("/documents/{publication_id}/fragments", response_model=list[FragmentOut])
def list_fragments(publication_id: str, page: int | None = Query(None, ge=1), limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    _get_or_404(db, Publication, publication_id, "Publication")
    stmt = select(SourceFragment).where(SourceFragment.publication_id == publication_id).order_by(SourceFragment.page, SourceFragment.position).limit(limit)
    if page is not None:
        stmt = stmt.where(SourceFragment.page == page)
    return [FragmentOut.model_validate({"id": x.id, "publication_id": x.publication_id, "page": x.page, "position": x.position, "text": x.text}) for x in db.scalars(stmt)]


@router.post("/documents/{publication_id}/analyze", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def analyze_document(publication_id: str, background: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    publication = _get_or_404(db, Publication, publication_id, "Publication")
    if publication.text_status == "no_text":
        raise HTTPException(status_code=422, detail="PDF contains no extractable text. OCR not yet supported")
    settings = request.app.state.settings
    job = ExtractionRun(
        id=str(uuid4()), publication_id=publication.id, status="queued",
        llm_mode=settings.llm_mode, llm_model="regex-demo" if settings.llm_mode == "mock" else settings.llm_model,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    response = _job_out(job)
    background.add_task(run_extraction, job.id, request.app.state.sessionmaker, settings)
    return response


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _job_out(_get_or_404(db, ExtractionRun, job_id, "Job"))


@router.get("/documents/{publication_id}/results", response_model=ResultsOut)
def document_results(publication_id: str, db: Session = Depends(get_db)):
    _get_or_404(db, Publication, publication_id, "Publication")
    job = db.scalar(select(ExtractionRun).where(ExtractionRun.publication_id == publication_id).order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc()).limit(1))
    return ResultsOut(publication_id=publication_id, latest_job=_job_out(job) if job else None, records=[_record_out(r) for r in job.records] if job else [])


@router.get("/results", response_model=list[RecordOut])
def list_records(domain: Domain | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(ResultRecord).order_by(ResultRecord.created_at.desc()).limit(limit)
    if domain:
        stmt = stmt.where(ResultRecord.domain == domain)
    return [_record_out(record) for record in db.scalars(stmt)]


@router.get("/results/{record_id}", response_model=RecordOut)
def get_record(record_id: str, db: Session = Depends(get_db)):
    return _record_out(_get_or_404(db, ResultRecord, record_id, "Result record"))


@router.get("/results/{record_id}/evidence", response_model=list[EvidenceOut])
def get_record_evidence(record_id: str, db: Session = Depends(get_db)):
    return _record_out(_get_or_404(db, ResultRecord, record_id, "Result record")).evidence


@router.get("/exports/json")
def export_json(domain: Domain | None = None, db: Session = Depends(get_db)):
    stmt = select(ResultRecord).order_by(ResultRecord.created_at)
    if domain:
        stmt = stmt.where(ResultRecord.domain == domain)
    return {"records": [_record_out(record).model_dump(mode="json") for record in db.scalars(stmt)]}
