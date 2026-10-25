from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.message import MessageRole
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_citation_repository import MessageCitationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageCitationResponse,
    MessageResponse,
)
from app.schemas.rag import ChatResponse, RagResponse

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_TOKEN_CHARS = 8000


class ConversationService:

    def __init__(self, db: Session):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.citation_repo = MessageCitationRepository(db)

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(
        self,
        user_id: int,
        title: str = "New Conversation",
        document_ids: list[int] | None = None,
    ) -> ConversationResponse:
        conversation = self.conversation_repo.create(
            user_id=user_id, title=title, document_ids=document_ids,
        )
        logger.info("Created conversation %s for user %s (docs=%s)", conversation.id, user_id, document_ids)
        return ConversationResponse.model_validate(conversation)

    def get_conversation(
        self,
        conversation_id: int,
        user_id: int,
    ) -> ConversationDetailResponse:
        conversation = self.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found")

        messages = self.message_repo.list_by_conversation(
            conversation_id, user_id,
        )

        message_responses = []
        for msg in messages:
            citation_models = self.citation_repo.list_by_message(msg.id)
            citations = [
                MessageCitationResponse.model_validate(c) for c in citation_models
            ]
            message_responses.append(
                MessageResponse(
                    id=msg.id,
                    conversation_id=msg.conversation_id,
                    role=msg.role.value,
                    content=msg.content,
                    abstained=msg.abstained,
                    abstention_reason=msg.abstention_reason,
                    confidence=msg.confidence,
                    created_at=msg.created_at,
                )
            )

        return ConversationDetailResponse(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=message_responses,
        )

    def list_conversations(
        self,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> ConversationListResponse:
        conversations = self.conversation_repo.list_by_user(
            user_id, offset, limit,
        )
        total = self.conversation_repo.count_by_user(user_id)

        return ConversationListResponse(
            conversations=[
                ConversationResponse.model_validate(c) for c in conversations
            ],
            total=total,
            offset=offset,
            limit=limit,
        )

    def update_conversation_title(
        self,
        conversation_id: int,
        user_id: int,
        title: str,
    ) -> ConversationResponse:
        conversation = self.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found")

        updated = self.conversation_repo.update_title(conversation, title)
        return ConversationResponse.model_validate(updated)

    def delete_conversation(
        self,
        conversation_id: int,
        user_id: int,
    ) -> None:
        conversation = self.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found")

        self.conversation_repo.delete_by_id_and_user(conversation_id, user_id)
        logger.info("Deleted conversation %s for user %s", conversation_id, user_id)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def save_user_message(
        self,
        conversation_id: int,
        user_id: int,
        content: str,
    ) -> MessageResponse:
        self._validate_ownership(conversation_id, user_id)

        message = self.message_repo.create(
            conversation_id=conversation_id,
            user_id=user_id,
            role=MessageRole.USER,
            content=content,
        )

        self.conversation_repo.touch(
            self.conversation_repo.get_by_id(conversation_id),
        )

        return MessageResponse.model_validate(message)

    def save_assistant_message(
        self,
        conversation_id: int,
        user_id: int,
        rag_response: RagResponse,
    ) -> MessageResponse:
        self._validate_ownership(conversation_id, user_id)

        answer = rag_response.answer or ""
        message = self.message_repo.create(
            conversation_id=conversation_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            rag_query=rag_response.query,
            abstained=rag_response.abstained,
            abstention_reason=rag_response.abstention_reason,
            confidence=rag_response.verdict.confidence_score,
        )

        if rag_response.evidence:
            citation_dicts = [
                {
                    "document_id": e.document_id,
                    "chunk_id": e.chunk_id,
                    "page_number": e.page_number,
                    "snippet": e.content[:500],
                    "score": float(e.rerank_score or e.score),
                }
                for e in rag_response.evidence
            ]
            self.citation_repo.create_many(message.id, citation_dicts)

        self.conversation_repo.touch(
            self.conversation_repo.get_by_id(conversation_id),
        )

        return MessageResponse.model_validate(message)

    def auto_title_from_query(
        self,
        conversation_id: int,
        user_id: int,
        query: str,
    ) -> None:
        """Set conversation title from the first user query (first 80 chars)."""
        conversation = self.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation is None:
            return

        title = query[:80].strip()
        if len(query) > 80:
            title += "..."
        self.conversation_repo.update_title(conversation, title)

    # ------------------------------------------------------------------
    # History context for LLM
    # ------------------------------------------------------------------

    def get_history_context(
        self,
        conversation_id: int,
        user_id: int,
    ) -> list[dict[str, str]]:
        """Return recent conversation history formatted for the LLM.

        Returns a list of {"role": "user"|"assistant", "content": "..."} dicts.
        Applies token budget to prevent context overflow.
        """
        messages = self.message_repo.list_by_conversation(
            conversation_id, user_id,
            limit=MAX_HISTORY_MESSAGES,
        )

        history: list[dict[str, str]] = []
        total_chars = 0

        for msg in reversed(messages):
            msg_chars = len(msg.content)
            if total_chars + msg_chars > MAX_HISTORY_TOKEN_CHARS:
                break
            history.insert(0, {
                "role": msg.role.value,
                "content": msg.content,
            })
            total_chars += msg_chars

        return history

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_ownership(
        self,
        conversation_id: int,
        user_id: int,
    ) -> None:
        conversation = self.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found")
