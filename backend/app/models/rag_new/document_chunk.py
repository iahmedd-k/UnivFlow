from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    page_numbers: Mapped[list] = mapped_column(
        sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    embedding = mapped_column(
        Vector(settings.embedding_dimension),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # NOTE: ``search_vector`` is a PostgreSQL GENERATED ALWAYS AS column
    # (added in migration 0006). It is NOT mapped to the ORM to prevent
    # SQLAlchemy from including it in INSERT statements. Access it via
    # ``DocumentChunk.__table__.c.search_vector`` in queries.