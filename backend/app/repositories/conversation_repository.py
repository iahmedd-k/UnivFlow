from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation


class ConversationRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        user_id: int,
        title: str = "New Conversation",
        document_ids: list[int] | None = None,
    ) -> Conversation:
        conversation = Conversation(
            user_id=user_id,
            title=title,
            document_ids=document_ids,
        )

        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)

        return conversation

    def get_by_id(self, conversation_id: int) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
        )

        return self.db.scalar(statement)

    def get_by_id_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )

        return self.db.scalar(statement)

    def list_by_user(
        self,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return list(self.db.scalars(statement))

    def count_by_user(self, user_id: int) -> int:
        from sqlalchemy import func

        statement = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user_id)
        )

        return self.db.scalar(statement)

    def update_title(
        self,
        conversation: Conversation,
        title: str,
    ) -> Conversation:
        conversation.title = title
        self.db.commit()
        self.db.refresh(conversation)

        return conversation

    def touch(self, conversation: Conversation) -> None:
        """Update the updated_at timestamp without changing content."""
        from datetime import datetime

        conversation.updated_at = datetime.utcnow()
        self.db.commit()

    def delete_by_id_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> Conversation | None:
        conversation = self.get_by_id_and_user(conversation_id, user_id)
        if conversation is None:
            return None

        self.db.delete(conversation)
        self.db.commit()

        return conversation
