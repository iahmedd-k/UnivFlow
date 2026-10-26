from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

def _resolve_engine_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_db_url = _resolve_engine_url(settings.database_url)
_connect_args = {"connect_timeout": 15} if _db_url and _db_url.startswith("postgresql") else {}
engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
)

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