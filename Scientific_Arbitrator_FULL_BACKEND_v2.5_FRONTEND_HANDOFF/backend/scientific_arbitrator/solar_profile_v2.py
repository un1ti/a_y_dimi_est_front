"""Solar scientific profile v2.

Conservative, source-grounded schema and dimensional checks.
Not a full certification protocol; never invent irradiance or measurement metadata.
"""
from __future__ import annotations

from math import isfinite

from .common import ArbitrationResult, ValidationIssue, ValidationReport, Verdict
from .schemas import SolarResult


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _same(a: object, b: object) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= max(1e-6, abs(float(a)) * 1e-6)
    return str(a).strip().casefold() == str(b).strip().casefold()


def expected_pce_pct(voc_v: float, jsc_ma_cm2: float, ff_pct: float, irradiance_mw_cm2: float) -> float:
    """PCE[%] = Voc[V] * Jsc[mA/cm2] * FF[%] / Pin[mW/cm2].

    Voc*Jsc is mW/cm2. FF[%]/100 is dimensionless. Divide by Pin and
    multiply by 100%, so the percentage factors cancel: Voc*Jsc*FF[%]/Pin.
    """
    for value in (voc_v, jsc_ma_cm2, ff_pct, irradiance_mw_cm2):
        if not isfinite(float(value)):
            raise ValueError("Non-finite photovoltaic quantity")
    if irradiance_mw_cm2 <= 0:
        raise ValueError("Irradiance must be positive")
    if voc_v < 0 or jsc_ma_cm2 < 0 or not (0 <= ff_pct <= 100):
        raise ValueError("Photovoltaic values outside valid ranges")
    return voc_v * jsc_ma_cm2 * ff_pct / irradiance_mw_cm2


def validate_solar_v2(record: SolarResult) -> ValidationReport:
    issues: list[ValidationIssue] = []

    def warn(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message, severity="warning"))

    def error(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message, severity="error"))

    if not record.evidence:
        warn("EVIDENCE_MISSING", "evidence", "No traceable source evidence attached.")
    if record.statistic is None:
        warn("STATISTIC_UNSPECIFIED", "statistic", "Best/mean/champion/median/range is unspecified.")
    if _missing(record.measurement_conditions):
        warn("MEASUREMENT_CONTEXT_MISSING", "measurement_conditions", "Spectral and other measurement context not established.")
    if _missing(record.absorber_material):
        warn("MATERIAL_UNSPECIFIED", "absorber_material", "Absorber material is not established (transport layer is not absorber).")
    if _missing(record.scan_direction):
        warn("SCAN_DIRECTION_UNSPECIFIED", "scan_direction", "Scan direction is not established; hysteresis cannot be assessed.")
    if record.active_area_cm2 is None:
        warn("ACTIVE_AREA_UNSPECIFIED", "active_area_cm2", "Active illuminated area is not established.")

    if record.metric.strip().upper() == "PCE":
        if record.light_intensity_mw_cm2 is None:
            warn("PCE_FORMULA_NOT_CHECKED", "light_intensity_mw_cm2",
                 "Irradiance is not independently source-supported; PCE/Voc/Jsc/FF consistency was not checked.")
        elif any(v is None for v in (record.voc_v, record.jsc_ma_cm2, record.ff_pct)):
            warn("PCE_COMPONENTS_MISSING", "pce_components",
                 "PCE/Voc/Jsc/FF consistency cannot be checked: one or more verified components are absent.")
        else:
            try:
                expected = expected_pce_pct(record.voc_v, record.jsc_ma_cm2,
                                            record.ff_pct, record.light_intensity_mw_cm2)
                tolerance = max(0.5, 0.1 * expected)  # rounding, precision and measurement variation
                if abs(record.value - expected) > tolerance:
                    error("PCE_PHYSICAL_INCONSISTENCY", "value",
                          f"Reported PCE {record.value:g}% differs from {expected:.3f}% calculated from source-supported Voc, Jsc, FF, and irradiance (tolerance {tolerance:.3f} percentage points).")
            except ValueError as exc:
                error("PCE_INVALID_COMPONENTS", "pce_components", str(exc))
    return ValidationReport(valid=not any(x.severity == "error" for x in issues), issues=issues)


def arbitrate_solar_v2(first: SolarResult, second: SolarResult) -> ArbitrationResult:
    """Compare measurement comparability; different device materials are experimental factors."""
    reasons: list[str] = []
    incompatible: list[str] = []
    missing: list[str] = []
    compared: list[str] = []
    if first.metric.strip().upper() != second.metric.strip().upper():
        incompatible.append("metric")
        reasons.append(f"Different metrics: {first.metric!r} vs {second.metric!r}.")
    compared.append("metric")
    if first.unit.strip().casefold() != second.unit.strip().casefold():
        incompatible.append("unit")
        reasons.append(f"Different units: {first.unit!r} vs {second.unit!r}.")
    compared.append("unit")

    # Comparing different absorbers/architectures may be exactly the experiment's goal.
    for field in ("statistic", "measurement_conditions", "scan_direction", "active_area_cm2"):
        av, bv = getattr(first, field), getattr(second, field)
        if _missing(av) or _missing(bv):
            missing.append(field)
        else:
            compared.append(field)
            if not _same(av, bv):
                incompatible.append(field)
                reasons.append(f"Different {field}: {av!r} vs {bv!r}.")

    if first.metric.strip().upper() == "PCE" and second.metric.strip().upper() == "PCE":
        av, bv = first.light_intensity_mw_cm2, second.light_intensity_mw_cm2
        if (av is None) != (bv is None):
            # One explicitly reports irradiance and the other does not.
            missing.append("light_intensity_mw_cm2")
        elif av is None and bv is None:
            # Missing both permits only a *provisional* context match, not a physics check.
            reasons.append("Irradiance is absent in both records; comparability is provisional and physical PCE checks were not performed.")
        else:
            compared.append("light_intensity_mw_cm2")
            if not _same(av, bv):
                incompatible.append("light_intensity_mw_cm2")
                reasons.append(f"Different irradiance: {av:g} vs {bv:g} mW/cm2.")

    if incompatible:
        if missing:
            reasons.append("Also missing context: " + ", ".join(missing) + ".")
        return ArbitrationResult(domain="solar", verdict=Verdict.INCOMPARABLE,
                                 reasons=reasons, blocking_fields=list(dict.fromkeys(incompatible + missing)),
                                 compared_fields=compared)
    if missing:
        return ArbitrationResult(domain="solar", verdict=Verdict.INSUFFICIENT_DATA,
                                 reasons=["Insufficient measurement context: " + ", ".join(missing) + "."],
                                 blocking_fields=missing, compared_fields=compared)
    return ArbitrationResult(domain="solar", verdict=Verdict.COMPARABLE,
                             reasons=["Measurement conditions, scan direction, statistic and area match; device differences can be compared but require expert interpretation."] + reasons,
                             compared_fields=compared)
