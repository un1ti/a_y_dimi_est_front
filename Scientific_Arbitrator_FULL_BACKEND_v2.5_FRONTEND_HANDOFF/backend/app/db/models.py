from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("sha256", "domain", name="uq_file_hash_domain"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str] = mapped_column(String(16), index=True)
    stored_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer)
    fragment_count: Mapped[int] = mapped_column(Integer)
    text_status: Mapped[str] = mapped_column(String(24), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fragments: Mapped[list[SourceFragment]] = relationship(back_populates="publication", cascade="all, delete-orphan")


class SourceFragment(Base):
    __tablename__ = "source_fragments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)  # 1-indexed page in the source PDF
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    publication: Mapped[Publication] = relationship(back_populates="fragments")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    llm_mode: Mapped[str] = mapped_column(String(20))
    llm_model: Mapped[str] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records: Mapped[list[ResultRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ResultRecord(Base):
    __tablename__ = "result_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(16), index=True)
    data_json: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(32), default="not_run")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped[ExtractionRun] = relationship(back_populates="records")
