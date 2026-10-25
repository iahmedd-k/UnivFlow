from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.models.user import User
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentResponse, DocumentStatusResponse
from app.schemas.response import ApiResponse
from app.services.chunking_service import ChunkingService
from app.services.docx_parser_service import DocxParserService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_parser_service import PdfParserService
from app.services.ppt_parser_service import PptParserService
from app.services.spreadsheet_parser_service import SpreadsheetParserService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    return DocumentService(
        document_repository=DocumentRepository(db),
        storage_service=StorageService(),
        pdf_parser_service=PdfParserService(),
        chunking_service=ChunkingService(),
        embedding_service=EmbeddingService(),
        document_chunk_repository=DocumentChunkRepository(db),
        spreadsheet_parser_service=SpreadsheetParserService(),
        ppt_parser_service=PptParserService(),
        docx_parser_service=DocxParserService(),
    )


@router.post(
    "",
    response_model=ApiResponse[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, CSV, Excel, PPTX, DOCX)",
)
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    # Stream the upload directly to a temp file on disk instead of reading
    # the entire payload into RAM (file.file.read() holds multiple copies).
    temp_dir = Path(settings.local_temp_dir) / f"user_{current_user.id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid4().hex
    ext = Path(file.filename or "").suffix.lower()
    temp_path = temp_dir / f"{file_id}{ext}"

    with open(temp_path, "wb") as buffer:
        while True:
            chunk = file.file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            buffer.write(chunk)

    file_size = temp_path.stat().st_size

    document, temp_path = document_service.upload_async(
        user_id=current_user.id,
        filename=file.filename or "",
        content_type=file.content_type,
        file_path=temp_path,
        file_size=file_size,
        public_id=f"docsense/users/{current_user.id}/{file_id}",
    )
    document = document_service._process(temp_path, document)
    return ApiResponse(
        success=True,
        data=document,
        message="Document uploaded and processed.",
    )


@router.get(
    "",
    response_model=ApiResponse[list[DocumentResponse]],
    summary="List the authenticated user's documents",
)
def list_documents(
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    results = document_service.list_documents(current_user.id)
    return ApiResponse(
        success=True,
        data=results,
        message=f"Found {len(results)} document(s).",
    )


@router.get(
    "/{document_id}/status",
    response_model=ApiResponse[DocumentStatusResponse],
    summary="Get a document's processing status",
)
def get_document_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    result = document_service.get_document_status(current_user.id, document_id)
    return ApiResponse(success=True, data=result, message="Document status retrieved.")


@router.get(
    "/{document_id}",
    response_model=ApiResponse[DocumentResponse],
    summary="Get one of the authenticated user's documents",
)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    result = document_service.get_document(current_user.id, document_id)
    return ApiResponse(success=True, data=result, message="Document retrieved.")


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its associated stored data",
)
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    document_service.delete_document(current_user.id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)