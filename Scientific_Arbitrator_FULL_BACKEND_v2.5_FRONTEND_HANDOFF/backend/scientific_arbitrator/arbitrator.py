from typing import Any
from .common import ArbitrationResult, Verdict
from .schemas import SolarResult, RAGResult


def _compare_context(a: Any, b: Any, fields: list[str], domain: str) -> ArbitrationResult:
    differences = []
    missing = []
    compared = []

    for field in fields:
        av = getattr(a, field)
        bv = getattr(b, field)
        if av is None or bv is None or av == "" or bv == "":
            missing.append(field)
        else:
            compared.append(field)
            if str(av).strip().casefold() != str(bv).strip().casefold():
                differences.append((field, av, bv))

    if differences:
        reasons = [
            f"Field '{field}' differs: first={av!r}, second={bv!r}."
            for field, av, bv in differences
        ]
        if missing:
            reasons.append("Additional context is missing for: " + ", ".join(missing) + ".")
        return ArbitrationResult(
            domain=domain,
            verdict=Verdict.INCOMPARABLE,
            reasons=reasons,
            blocking_fields=[x[0] for x in differences] + missing,
            compared_fields=compared,
        )

    if missing:
        return ArbitrationResult(
            domain=domain,
            verdict=Verdict.INSUFFICIENT_DATA,
            reasons=["Cannot establish comparability because required context is missing: "
                     + ", ".join(missing) + "."],
            blocking_fields=missing,
            compared_fields=compared,
        )

    return ArbitrationResult(
        domain=domain,
        verdict=Verdict.COMPARABLE,
        reasons=["All mandatory comparison fields in this prototype match."],
        compared_fields=compared,
    )


def arbitrate_solar(first: SolarResult, second: SolarResult) -> ArbitrationResult:
    from .solar_profile_v2 import arbitrate_solar_v2
    return arbitrate_solar_v2(first, second)



def arbitrate_rag(first: RAGResult, second: RAGResult) -> ArbitrationResult:
    from .rag_profile_v2 import arbitrate_rag_v2
    return arbitrate_rag_v2(first, second)



def arbitrate(domain: str, first: dict, second: dict) -> ArbitrationResult:
    domain = domain.strip().lower()
    if domain == "solar":
        return arbitrate_solar(SolarResult.model_validate(first), SolarResult.model_validate(second))
    if domain == "rag":
        return arbitrate_rag(RAGResult.model_validate(first), RAGResult.model_validate(second))
    raise ValueError(f"Unsupported domain: {domain}")
