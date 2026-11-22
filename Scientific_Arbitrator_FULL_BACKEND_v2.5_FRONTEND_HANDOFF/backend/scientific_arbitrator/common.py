from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Verdict(str, Enum):
    COMPARABLE = "comparable"
    INCOMPARABLE = "incomparable"
    INSUFFICIENT_DATA = "insufficient_data"


class Evidence(StrictModel):
    source_id: str = Field(min_length=1)
    document_title: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    locator: Optional[str] = None
    quote: Optional[str] = None
    raw_value: Optional[str] = None
    raw_unit: Optional[str] = None
    extraction_method: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("source_id")
    @classmethod
    def source_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_id must not be blank")
        return value


class ValidationIssue(StrictModel):
    code: str
    message: str
    severity: str = "error"
    field: Optional[str] = None


class ValidationReport(StrictModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class ArbitrationResult(StrictModel):
    domain: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    blocking_fields: list[str] = Field(default_factory=list)
    compared_fields: list[str] = Field(default_factory=list)
    note: str = (
        "Automated rule-based assessment; not a substitute for expert scientific review."
    )
