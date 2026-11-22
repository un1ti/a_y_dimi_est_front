"""Shared contract with backend developer #2. Null means "not present in evidence"."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Domain = Literal["solar", "rag"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(description="Name of field supported by this evidence")
    fragment_id: str = Field(description="Exact ID of a supplied text fragment")
    quote: str = Field(min_length=1, description="Verbatim substring from the cited fragment")


class FindingBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: list[EvidenceRef] = Field(default_factory=list)


class SolarFinding(FindingBase):
    material_name: str | None = None
    material_class: str | None = None
    device_label: str | None = None
    device_type: str | None = None
    architecture: str | None = None
    active_area_cm2: float | None = None
    spectrum: str | None = None
    light_intensity_mw_cm2: float | None = None
    scan_direction: str | None = None
    aggregation: str | None = None  # champion, mean, median etc.
    pce_pct: float | None = None
    voc_v: float | None = None
    jsc_ma_cm2: float | None = None
    ff_pct: float | None = None
    bandgap_ev: float | None = None
    jsc_eqe_ma_cm2: float | None = None


class RagFinding(FindingBase):
    config_label: str | None = None
    rag_variant: str | None = None
    retrieval_method: str | None = None
    retriever_model: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    chunking_method: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_unit: str | None = None
    index_type: str | None = None
    vector_store: str | None = None
    top_k: int | None = None
    reranker_model: str | None = None
    generator_model: str | None = None
    generator_version: str | None = None
    prompt_strategy: str | None = None
    context_strategy: str | None = None
    dataset_name: str | None = None
    dataset_version: str | None = None
    task_type: str | None = None
    language: str | None = None
    data_split: str | None = None
    scientific_domain: str | None = None
    evaluation_protocol: str | None = None
    baseline_name: str | None = None
    metric_name: str | None = None
    metric_variant: str | None = None
    metric_direction: str | None = None
    metric_k: int | None = None
    metric_value: float | None = None
    metric_unit: str | None = None
    baseline_value: float | None = None
    aggregation: str | None = None
    sample_size: int | None = None
    latency_ms: float | None = None
    tokens_per_query: float | None = None


class SolarOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[SolarFinding] = Field(default_factory=list)


class RagOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[RagFinding] = Field(default_factory=list)
