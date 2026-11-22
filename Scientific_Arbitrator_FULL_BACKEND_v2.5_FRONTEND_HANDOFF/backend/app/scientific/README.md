# Integration zone for backend developer #2

**Do not move source parsing and API code into this folder.**

Suggested public functions (same shared `app.schemas.domain` types):

```python
# app/scientific/solar_validator.py
def validate_solar(record: SolarFinding) -> list[ValidationIssue]: ...
# app/scientific/rag_validator.py
def validate_rag(record: RagFinding) -> list[ValidationIssue]: ...
# app/scientific/comparison.py
def compare_solar(a: SolarFinding, b: SolarFinding) -> ComparisonDecision: ...
def compare_rag(a: RagFinding, b: RagFinding) -> ComparisonDecision: ...
```

The current service stores `validation_status="not_run"`; this is deliberate, not a green check.

On integration, call validators **after** schema validation and before final result persistence in `app/services/analysis.py`. Preserve extracted values and store remarks separately; never alter LLM output as a side-effect of validation. For comparisons, add `POST /api/v1/comparisons` once the comparison module is implemented and tested.

Pydantic contracts: `app/schemas/domain.py`, `app/schemas/api.py`.

`EvidenceOut.verification='quote_matched'` checks literal quote presence only, not scientific correctness.
