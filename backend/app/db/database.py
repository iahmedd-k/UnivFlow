from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

def get_database_url() -> str:
    if settings.database_url and settings.database_url.startswith("postgresql"):
        # Ensure psycopg2 driver is used for PostgreSQL
        if settings.database_url.startswith("postgresql://"):
            return settings.database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if settings.database_url.startswith("postgresql+psycopg://"):
            return settings.database_url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
        return settings.database_url
    if settings.supabase_db_url:
        url = settings.supabase_db_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
        return url
    return "sqlite:///./uniflow.db"

database_url = get_database_url()

def create_engine_with_fallback(url: str):
    """Create the configured database engine without silently changing databases."""
    if url.startswith("postgresql"):
        engine = create_engine(
            url,
            echo=settings.database_echo,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connected to PostgreSQL database")
        except Exception as conn_err:
            logger.warning(f"PostgreSQL initial ping warning (will retry on demand): {conn_err}")
        return engine
    else:
        return create_engine(
            url,
            echo=settings.database_echo,
            pool_pre_ping=True,
            poolclass=NullPool,
        )

engine = create_engine_with_fallback(database_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
