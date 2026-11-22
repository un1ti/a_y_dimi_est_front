"""Background extraction job. Owns no scientific validation rules."""
from __future__ import annotations

import json
import os
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import ExtractionRun, Publication, ResultRecord, SourceFragment, utcnow
from app.schemas.domain import RagOutput, SolarOutput
from app.services.llm import make_provider
from app.services.grounding import ground_record
from app.services.retrieval import find_relevant_fragments
from app.services.extraction_profile import select_scientific_fragments
from app.services.rag_output_compat import normalize_rag_payload


def run_extraction(job_id: str, sessions: sessionmaker[Session], settings: Settings) -> None:
    # New session in worker thread; do not pass request-scoped session to BackgroundTasks.
    with sessions() as db:
        try:
            job = db.get(ExtractionRun, job_id)
            if job is None:
                return
            job.status = "running"
            db.commit()
            publication = db.get(Publication, job.publication_id)
            if publication is None:
                raise ValueError("Publication no longer exists")
            if publication.text_status == "no_text":
                raise ValueError("No extractable text; OCR is not enabled in this MVP")
            fragments = list(db.scalars(select(SourceFragment).where(SourceFragment.publication_id == publication.id).order_by(SourceFragment.page, SourceFragment.position)))
            selected = select_scientific_fragments(fragments, publication.domain, settings)
            # RAG v2.2: structurally linked table cells first, LLM only as fallback.
            # This is opt-out via RAG_TABLE_MODE=off; no change to Solar.
            if publication.domain == "rag" and os.getenv("RAG_TABLE_MODE", "prefer").lower() == "prefer":
                from app.services.rag_table_extraction import extract_rag_table_records
                from app.services.rag_pdf_table_recovery import recover_text_aligned_tables
                parsed_table = extract_rag_table_records(fragments)
                if not parsed_table.records:
                    pdf_path = settings.data_dir / "uploads" / f"{publication.id}.pdf"
                    if pdf_path.is_file():
                        recovered = recover_text_aligned_tables(
                            pdf_path.read_bytes(), max_pages=settings.max_pdf_pages)
                        seen_texts = {(f.page, f.text) for f in fragments}
                        next_pos = {}
                        for f in fragments:
                            next_pos[f.page] = max(next_pos.get(f.page, 0), f.position)
                        for table_frag in recovered:
                            if (table_frag.page, table_frag.text) in seen_texts:
                                continue
                            seen_texts.add((table_frag.page, table_frag.text))
                            page = table_frag.page
                            next_pos[page] = next_pos.get(page, 0) + 1
                            stored = SourceFragment(
                                id=str(uuid4()), publication_id=publication.id,
                                page=page, position=next_pos[page], text=table_frag.text,
                            )
                            db.add(stored)
                            fragments.append(stored)
                            publication.fragment_count += 1
                        if recovered:
                            db.flush()
                            parsed_table = extract_rag_table_records(fragments)
                if parsed_table.records:
                    data = {"records": parsed_table.records}
                    # The run has used no model; record true extraction provenance.
                    job.llm_mode = "table"
                    job.llm_model = "deterministic-pdf-table-v2.2"
                    # Grounding must know IDs of persisted table fragments.
                    selected = fragments
                else:
                    data = make_provider(settings).extract(publication.domain, selected)
            else:
                data = make_provider(settings).extract(publication.domain, selected)
            if publication.domain == "rag":
                data = normalize_rag_payload(data)
            payload = (SolarOutput if publication.domain == "solar" else RagOutput).model_validate(data)
            refs = {fragment.id: fragment for fragment in selected}
            stored_count = 0
            for finding in payload.records:
                record_data, evidence, removed_fields = ground_record(finding, refs)
                # Never save a record whose non-null fields have no verified citations.
                if not evidence:
                    continue
                db.add(ResultRecord(
                    id=str(uuid4()),
                    run_id=job.id,
                    publication_id=publication.id,
                    domain=publication.domain,
                    data_json=json.dumps(record_data, ensure_ascii=False),
                    evidence_json=json.dumps(evidence, ensure_ascii=False),
                    # This is traceability, NOT completed scientific validation.
                    validation_status="not_run",
                ))
                stored_count += 1
            if payload.records and stored_count == 0:
                raise ValueError("Model records lacked source-supported evidence. Nothing saved")
            job.status = "done"
            job.finished_at = utcnow()
            job.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ExtractionRun, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {str(exc)[:700]}"
                job.finished_at = utcnow()
                db.commit()
