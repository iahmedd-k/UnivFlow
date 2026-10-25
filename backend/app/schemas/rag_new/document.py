from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: int
    user_id: int
    original_filename: str
    storage_key: str
    storage_url: str
    mime_type: str
    file_size: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    document_id: int
    status: DocumentStatus