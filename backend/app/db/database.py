from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError
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
    """Create engine with fallback to SQLite if PostgreSQL fails"""
    if url.startswith("postgresql"):
        try:
            engine = create_engine(
                url,
                echo=settings.database_echo,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=300,
            )
            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connected to PostgreSQL database")
            return engine
        except OperationalError as e:
            logger.warning(f"PostgreSQL connection failed, falling back to SQLite: {e}")
            sqlite_url = "sqlite:///./uniflow.db"
            return create_engine(
                sqlite_url,
                echo=settings.database_echo,
                pool_pre_ping=True,
                poolclass=NullPool,
            )
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