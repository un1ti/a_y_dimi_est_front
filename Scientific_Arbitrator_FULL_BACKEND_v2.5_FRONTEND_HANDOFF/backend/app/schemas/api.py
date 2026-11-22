from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from .domain import Domain


class DomainInfo(BaseModel):
    code: Domain
    label: str
    description: str


class DocumentOut(BaseModel):
    id: str
    filename: str
    sha256: str
    domain: Domain
    page_count: int
    fragment_count: int
    text_status: str
    created_at: datetime
    created: bool = True


class FragmentOut(BaseModel):
    id: str
    publication_id: str
    page: int
    position: int
    text: str


class JobOut(BaseModel):
    id: str
    publication_id: str
    status: Literal["queued", "running", "done", "failed"]
    llm_mode: str
    llm_model: str
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    record_count: int = 0


class EvidenceOut(BaseModel):
    field: str
    fragment_id: str
    page: int
    quote: str
    verification: Literal["quote_matched", "quote_not_matched"]


class RecordOut(BaseModel):
    id: str
    run_id: str
    publication_id: str
    domain: Domain
    data: dict[str, Any]
    evidence: list[EvidenceOut] = Field(default_factory=list)
    validation_status: str
    created_at: datetime


class ResultsOut(BaseModel):
    publication_id: str
    latest_job: JobOut | None
    records: list[RecordOut]
