from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    snippet: Mapped[str] = mapped_column(
        nullable=True,
    )

    score: Mapped[float | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
