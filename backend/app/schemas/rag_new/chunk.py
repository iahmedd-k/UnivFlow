from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """An in-memory chunk of structured document content.

    Chunks are transient processing objects produced during ingestion; they are
    persisted (with their vector embedding) to PostgreSQL by the document
    processing pipeline.
    """

    chunk_id: str
    document_id: int
    page_number: int
    page_numbers: list[int] = Field(default_factory=list)
    content: str
    content_type: str
    metadata: dict = Field(default_factory=dict)
