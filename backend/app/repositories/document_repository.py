from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus


class DocumentRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        user_id: int,
        original_filename: str,
        storage_key: str,
        storage_url: str,
        mime_type: str,
        file_size: int,
        status: DocumentStatus = DocumentStatus.UPLOADED,
    ) -> Document:

        document = Document(
            user_id=user_id,
            original_filename=original_filename,
            storage_key=storage_key,
            storage_url=storage_url,
            mime_type=mime_type,
            file_size=file_size,
            status=status,
        )

        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        return document

    def get_by_id(self, document_id: int) -> Document | None:
        statement = select(Document).where(Document.id == document_id)

        return self.db.scalar(statement)

    def get_by_id_and_user(
        self,
        document_id: int,
        user_id: int,
    ) -> Document | None:
        statement = select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )

        return self.db.scalar(statement)

    def list_by_user(self, user_id: int) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )

        return list(self.db.scalars(statement))

    def fail_stale_processing(self, user_id: int, older_than: datetime) -> int:
        """Mark stale in-progress uploads failed with one user-scoped write."""
        statement = (
            update(Document)
            .where(
                Document.user_id == user_id,
                Document.status.in_((DocumentStatus.UPLOADED, DocumentStatus.PROCESSING)),
                Document.updated_at < older_than,
            )
            .values(status=DocumentStatus.FAILED, updated_at=datetime.utcnow())
        )
        result = self.db.execute(statement)
        if result.rowcount:
            self.db.commit()
        return result.rowcount or 0

    def update_status(
        self,
        document: Document,
        status: DocumentStatus,
    ) -> Document:
        document.status = status
        self.db.commit()
        self.db.refresh(document)

        return document

    def delete_by_id_and_user(
        self,
        document_id: int,
        user_id: int,
    ) -> Document | None:
        """Delete a document owned by the user and return it, or None if not found."""
        document = self.get_by_id_and_user(document_id, user_id)
        if document is None:
            return None

        self.db.delete(document)
        self.db.commit()

        return document
