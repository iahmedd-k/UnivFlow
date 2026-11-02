"""Compatibility exports for the canonical database engine and sessions.

All application code must share the engine configured in ``database.py`` so
routers and background services share one bounded connection pool.
"""

from app.db.database import Base, SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
