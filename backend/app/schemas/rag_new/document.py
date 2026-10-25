from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: Union[int, str]
    user_id: Optional[Union[int, str]] = None
    original_filename: str
    clean_title: Optional[str] = None
    storage_key: Optional[str] = None
    storage_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = 0
    status: Union[DocumentStatus, str] = DocumentStatus.COMPLETED
    chunk_count: Optional[int] = None
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    category: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    document_id: Union[int, str]
    status: Union[DocumentStatus, str]