from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message_citation import MessageCitation


class MessageCitationRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        message_id: int,
        document_id: int,
        page_number: int,
        snippet: str | None = None,
        chunk_id: int | None = None,
        score: float | None = None,
    ) -> MessageCitation:
        citation = MessageCitation(
            message_id=message_id,
            document_id=document_id,
            page_number=page_number,
            snippet=snippet,
            chunk_id=chunk_id,
            score=score,
        )

        self.db.add(citation)
        self.db.commit()
        self.db.refresh(citation)

        return citation

    def create_many(
        self,
        message_id: int,
        citations: list[dict],
    ) -> list[MessageCitation]:
        objects = [
            MessageCitation(message_id=message_id, **c)
            for c in citations
        ]

        self.db.add_all(objects)
        self.db.commit()

        for obj in objects:
            self.db.refresh(obj)

        return objects

    def list_by_message(
        self,
        message_id: int,
    ) -> list[MessageCitation]:
        statement = (
            select(MessageCitation)
            .where(MessageCitation.message_id == message_id)
            .order_by(MessageCitation.id.asc())
        )

        return list(self.db.scalars(statement))

    def delete_by_message(self, message_id: int) -> None:
        statement = select(MessageCitation).where(
            MessageCitation.message_id == message_id,
        )

        citations = list(self.db.scalars(statement))
        for cit in citations:
            self.db.delete(cit)

        self.db.commit()
