from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

# Paths are always resolved relative to the project (not your terminal cwd).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _default_data_dir() -> Path:
    raw = Path(os.getenv("DATA_DIR", "./.data")).expanduser()
    return (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    database_url: str | None = None
    llm_mode: str = field(default_factory=lambda: os.getenv("LLM_MODE", "mock"))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://127.0.0.1:8001/v1"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "local-model"))
    llm_json_mode: bool = field(default_factory=lambda: os.getenv("LLM_JSON_MODE", "true").lower() == "true")
    llm_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "120")))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "15")))
    max_pdf_pages: int = field(default_factory=lambda: int(os.getenv("MAX_PDF_PAGES", "120")))
    max_prompt_chars: int = field(default_factory=lambda: int(os.getenv("MAX_PROMPT_CHARS", "18000")))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()))

    @property
    def db_url(self) -> str:
        return self.database_url or os.getenv("DATABASE_URL") or f"sqlite:///{self.data_dir / 'arbitrator.sqlite3'}"
