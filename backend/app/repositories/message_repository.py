from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message import Message, MessageRole


class MessageRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        conversation_id: int,
        user_id: int,
        role: MessageRole,
        content: str,
        rag_query: str | None = None,
        abstained: bool | None = None,
        abstention_reason: str | None = None,
        confidence: float | None = None,
        tokens_used: int | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            rag_query=rag_query,
            abstained=abstained,
            abstention_reason=abstention_reason,
            confidence=confidence,
            tokens_used=tokens_used,
        )

        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)

        return message

    def get_by_id(self, message_id: int) -> Message | None:
        statement = select(Message).where(Message.id == message_id)

        return self.db.scalar(statement)

    def get_by_id_and_user(
        self,
        message_id: int,
        user_id: int,
    ) -> Message | None:
        statement = select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )

        return self.db.scalar(statement)

    def list_by_conversation(
        self,
        conversation_id: int,
        user_id: int,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Message]:
        statement = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.user_id == user_id,
            )
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
        )

        return list(self.db.scalars(statement))

    def count_by_conversation(
        self,
        conversation_id: int,
    ) -> int:
        from sqlalchemy import func

        statement = (
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )

        return self.db.scalar(statement)

    def delete_by_conversation(
        self,
        conversation_id: int,
    ) -> None:
        statement = select(Message).where(
            Message.conversation_id == conversation_id,
        )

        messages = list(self.db.scalars(statement))
        for msg in messages:
            self.db.delete(msg)

        self.db.commit()
