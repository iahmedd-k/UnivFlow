from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    title: str = Field(
        default="New Conversation",
        max_length=255,
        description="Conversation title",
    )
    document_ids: list[int] | None = Field(
        default=None,
        description="Optional list of document IDs to scope this conversation to",
    )


class ConversationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    document_ids: list[int] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    abstained: bool | None = None
    abstention_reason: str | None = None
    confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCitationResponse(BaseModel):
    id: int
    document_id: int
    page_number: int
    snippet: str | None = None
    score: float | None = None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: int
    user_id: int
    title: str
    document_ids: list[int] | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    offset: int = Field(..., ge=0)
    limit: int = Field(..., ge=0)


class ConversationUpdateRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="New conversation title",
    )


class MessageWithContext(BaseModel):
    """A message with its citations, used when loading history for the LLM."""

    role: str
    content: str
    citations: list[MessageCitationResponse] = Field(default_factory=list)
