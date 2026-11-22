from app.api.rag_profile_routes import router as rag_profile_router
from app.api.rag_table_routes import router as rag_table_router
from app.api.quality_routes import router as quality_router
from app.api.report_routes import router as report_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.search_routes import router as search_router
from app.api.scientific_routes import router as scientific_router
from app.config import Settings
from app.db.models import Base
from app.db.session import make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sessions = make_sessionmaker(settings.db_url)
    Base.metadata.create_all(bind=sessions.kw["bind"])

    app = FastAPI(title="The Scientific Arbitrator API", version="0.1.0", description="Two-domain scientific PDF extraction API. Regex mock and OpenAI-compatible provider. Scientific validation is delegated to developer #2.")
    app.state.settings = settings
    app.state.sessionmaker = sessions
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(search_router)
    app.include_router(scientific_router)
    app.include_router(rag_profile_router)
    app.include_router(rag_table_router)
    app.include_router(quality_router)
    app.include_router(report_router)
    return app


app = create_app()
