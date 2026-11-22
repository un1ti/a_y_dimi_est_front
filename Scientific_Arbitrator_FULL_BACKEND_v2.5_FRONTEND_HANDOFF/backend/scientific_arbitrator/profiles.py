from dataclasses import dataclass
from typing import Type
from pydantic import BaseModel
from .schemas import SolarResult, RAGResult
from .validation import validate_solar, validate_rag


@dataclass(frozen=True)
class DomainProfile:
    name: str
    schema: Type[BaseModel]
    validator: object


PROFILES = {
    "solar": DomainProfile("Solar Research", SolarResult, validate_solar),
    "rag": DomainProfile("RAG Research", RAGResult, validate_rag),
}


def get_profile(domain: str) -> DomainProfile:
    try:
        return PROFILES[domain.strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown domain profile: {domain}")
