from .common import ValidationReport, ValidationIssue
from .schemas import SolarResult, RAGResult


def validate_solar(record: SolarResult) -> ValidationReport:
    from .solar_profile_v2 import validate_solar_v2
    return validate_solar_v2(record)



def validate_rag(record: RAGResult) -> ValidationReport:
    from .rag_profile_v2 import validate_rag_v2
    return validate_rag_v2(record)

