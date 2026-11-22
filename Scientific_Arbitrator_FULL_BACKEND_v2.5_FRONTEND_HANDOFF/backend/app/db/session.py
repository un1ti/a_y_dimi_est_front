from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessionmaker(db_url: str) -> sessionmaker[Session]:
    is_sqlite = db_url.startswith("sqlite")
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if is_sqlite else {}, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.sessionmaker() as session:
        yield session
