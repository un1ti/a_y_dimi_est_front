from typing import Optional, Literal
from pydantic import Field, field_validator, model_validator
from .common import StrictModel, Evidence


class SolarResult(StrictModel):
    domain: Literal["solar"] = "solar"
    study_id: str = Field(min_length=1)
    device_id: Optional[str] = None
    absorber_material: Optional[str] = None
    architecture: Optional[str] = None
    metric: str
    value: float
    unit: str
    statistic: Optional[Literal["best", "mean", "median", "champion", "range"]] = None
    sample_size: Optional[int] = Field(default=None, ge=1)
    measurement_conditions: Optional[str] = None
    scan_direction: Optional[str] = None
    active_area_cm2: Optional[float] = Field(default=None, gt=0)
    stability_protocol: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)
    # Source-supported raw components used only for conditional PCE consistency.
    voc_v: Optional[float] = Field(default=None, ge=0)
    jsc_ma_cm2: Optional[float] = Field(default=None, ge=0)
    ff_pct: Optional[float] = Field(default=None, ge=0, le=100)
    light_intensity_mw_cm2: Optional[float] = Field(default=None, gt=0)

    @field_validator("study_id", "metric", "unit")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("value must be finite")
        return value

    @model_validator(mode="after")
    def metric_unit_sanity(self):
        metric = self.metric.strip().upper()
        unit = self.unit.strip()
        if metric == "PCE":
            if unit not in {"%", "percent"}:
                raise ValueError("PCE must use '%' or 'percent' in this prototype")
            if not 0 <= self.value <= 100:
                raise ValueError("PCE must be between 0 and 100 percent")
        if metric == "FF":
            if unit not in {"%", "percent"}:
                raise ValueError("FF must use '%' or 'percent' in this prototype")
            if not 0 <= self.value <= 100:
                raise ValueError("FF must be between 0 and 100 percent")
        if metric == "VOC" and self.value < 0:
            raise ValueError("Voc cannot be negative")
        if metric == "JSC" and self.value < 0:
            raise ValueError("Jsc cannot be negative")
        return self


class RAGResult(StrictModel):
    domain: Literal["rag"] = "rag"
    study_id: str = Field(min_length=1)
    system_id: Optional[str] = None
    llm: Optional[str] = None
    embedding_model: Optional[str] = None
    retriever: Optional[str] = None
    reranker: Optional[str] = None
    chunking_strategy: Optional[str] = None
    metric: str
    value: float
    k: Optional[int] = Field(default=None, ge=1)
    dataset: Optional[str] = None
    evaluation_protocol: Optional[str] = None
    split: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("study_id", "metric")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @model_validator(mode="after")
    def metric_sanity(self):
        metric = self.metric.strip().lower()
        if metric in {"recall", "precision", "f1", "mrr", "ndcg"}:
            if not 0 <= self.value <= 1:
                raise ValueError(f"{self.metric} must be in [0, 1] in this prototype")
        return self
