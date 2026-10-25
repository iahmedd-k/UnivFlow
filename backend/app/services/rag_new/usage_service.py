from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.message import Message, MessageRole
from app.schemas.usage import UsageResponse


class UsageService:
    """Returns the authenticated user's current usage and quota information (FR-022).

    Quotas are calibrated for live portfolio showcase limits. Current usage is
    computed directly from the database scoped to the requesting user.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_usage(self, user_id: int) -> UsageResponse:
        documents_uploaded = self._count_documents(user_id)
        chunks_stored = self._count_chunks(user_id)
        queries_used = self._count_queries(user_id)

        return UsageResponse(
            user_id=user_id,
            documents_uploaded=documents_uploaded,
            document_quota=5,
            chunks_stored=chunks_stored,
            chunk_quota=-1,
            queries_this_month=queries_used,
            query_quota=7,
        )

    def _count_documents(self, user_id: int) -> int:
        statement = select(func.count()).select_from(Document).where(
            Document.user_id == user_id
        )
        return self.db.scalar(statement) or 0

    def _count_chunks(self, user_id: int) -> int:
        statement = select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.user_id == user_id
        )
        return self.db.scalar(statement) or 0

    def _count_queries(self, user_id: int) -> int:
        statement = select(func.count()).select_from(Message).where(
            Message.user_id == user_id,
            Message.role == MessageRole.USER,
        )
        return self.db.scalar(statement) or 0
