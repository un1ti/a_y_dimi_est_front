"""Read-only RAG audit. Latest successful run by default, optional historical scope."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExtractionRun, Publication, ResultRecord
from app.db.session import get_db
from scientific_arbitrator.rag_audit_v21 import audit_records

router = APIRouter(prefix='/api/v1/scientific/rag', tags=['RAG Profile v2.1'])


@router.get('/audit')
def audit(publication_id: str, scope: Literal['latest', 'all'] = 'latest',
          db: Session = Depends(get_db)):
    publication = db.get(Publication, publication_id)
    if publication is None or publication.domain != 'rag':
        raise HTTPException(404, 'RAG publication not found')
    latest = db.scalar(select(ExtractionRun).where(
        ExtractionRun.publication_id == publication_id, ExtractionRun.status == 'done',
    ).order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc()).limit(1))
    stmt = select(ResultRecord).where(
        ResultRecord.publication_id == publication_id, ResultRecord.domain == 'rag',
    )
    if scope == 'latest':
        if latest is None:
            return {'publication_id': publication_id, 'scope': scope, 'run_id': None,
                    **audit_records([])}
        stmt = stmt.where(ResultRecord.run_id == latest.id)
    records = db.scalars(stmt.order_by(ResultRecord.created_at, ResultRecord.id)).all()
    return {'publication_id': publication_id, 'scope': scope,
            'run_id': latest.id if scope == 'latest' and latest else None,
            **audit_records([
                {'id': rec.id, 'data': json.loads(rec.data_json),
                 'evidence': json.loads(rec.evidence_json)}
                for rec in records
            ])}
