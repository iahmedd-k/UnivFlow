from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ExportWebChatRequest(BaseModel):
    url: str = Field(
        ...,
        description="Public or private chat URL from ChatGPT (chatgpt.com), Claude (claude.ai), or Gemini (gemini.google.com)",
    )
    custom_title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional custom title for the resulting PDF",
    )
    auto_index: bool = Field(
        default=False,
        description="Whether to automatically index extracted conversation messages into the RAG knowledge base",
    )


class ExportedChatUpdateRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="New title for the exported chat PDF",
    )


class ExportedChatResponse(BaseModel):
    id: int
    user_id: str
    title: str
    source_platform: str
    source_url: str
    is_public: bool
    turn_count: int
    has_images: bool
    has_diagrams: bool
    file_url: Optional[str] = None
    google_drive_url: Optional[str] = None
    file_size_bytes: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ExportedChatListResponse(BaseModel):
    items: list[ExportedChatResponse]
    total: int

