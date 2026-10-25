from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

def _resolve_engine_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


_db_url = _resolve_engine_url(settings.database_url)
engine = create_engine(_db_url, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()