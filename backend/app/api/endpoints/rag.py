import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, load_only

from app.api.endpoints.rag_helpers import (
    _classify_file_type,
    _classify_material,
    list_classroom_materials,
    _read_materials,
    _retrieve_passages,
    upload_study_material,
)
from app.auth.clerk_auth import require_current_user
from app.auth.ownership import user_owner_ids
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Assignment, AssignmentMaterial, Course
from app.models.document import Document, DocumentStatus
from app.models.message import Message, MessageRole
from app.models.user import User, UserRole
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.rag_new.chat import StreamChatRequest
from app.schemas.rag_new.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCitationResponse,
    MessageResponse,
)
from app.schemas.rag_new.document import DocumentResponse, DocumentStatusResponse
from app.core.redis import invalidate_user_cache, invalidate_user_caches
from app.schemas.rag_new.rag import ChatResponse, RagRequest, SourceChunk, SourceCitation
from app.schemas.rag_new.response import ApiResponse
from app.schemas.rag_new.retrieval import ChunkResult, SearchApiResponse
from app.schemas.rag_new.usage import UsageResponse
from app.services.gemini import generate_study_answer
from app.services.rag_new.chat_service import ChatService
from app.services.rag_new.chunking_service import ChunkingService
from app.services.rag_new.conversation_service import ConversationService
from app.services.rag_new.document_service import DocumentService
from app.services.rag_new.docx_parser_service import DocxParserService
from app.services.rag_new.embedding_service import EmbeddingService
from app.services.rag_new.llm_service import LLMService
from app.services.rag_new.pdf_parser_service import PdfParserService
from app.services.rag_new.ppt_parser_service import PptParserService
from app.services.rag_new.query_analysis_service import QueryAnalysisService
from app.services.rag_new.rag_service import RAGService
from app.services.rag_new.reranking_service import RerankingService
from app.services.rag_new.retrieval_service import (
    LexicalRetrievalService,
    RetrievalMethod,
    RetrievalService,
    VectorRetrievalService,
)
from app.services.rag_new.rrf_service import RRFService
from app.services.rag_new.spreadsheet_parser_service import SpreadsheetParserService
from app.services.rag_new.storage_service import StorageService
from app.services.rag_new.usage_service import UsageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


# --- Helper: User Context Resolution ---

def resolve_user_context(db: Session, current_user: dict) -> tuple[int, str]:
    """Resolve (db_user_id: int, clerk_user_id: str).

    Ensures a corresponding integer record in users table exists so foreign keys
    (conversations.user_id, messages.user_id, documents.user_id) never fail.
    """
    clerk_id = current_user.get("id") or "dev_student_user"
    email = current_user.get("email") or f"{clerk_id}@uniflow.app"

    user = db.query(User).filter(User.email == email).first()
    if not user and clerk_id.startswith("dev_"):
        user = db.query(User).filter(User.id == 1).first()

    if not user:
        name_parts = (current_user.get("name") or "Student User").split()
        first = name_parts[0] if name_parts else "Student"
        last = " ".join(name_parts[1:]) if len(name_parts) > 1 else "User"
        user = User(
            first_name=first,
            last_name=last,
            email=email,
            password_hash="oauth_session",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            user = db.query(User).filter(User.email == email).first() or db.query(User).filter(User.id == 1).first()

    return (user.id if user else 1), str(clerk_id)


# --- Dependencies ---

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


def get_retrieval_service(db: Session = Depends(get_db)) -> RetrievalService:
    chunk_repository = DocumentChunkRepository(db)
    vector_retrieval_service = VectorRetrievalService(
        embedding_service=EmbeddingService(),
        chunk_repository=chunk_repository,
    )
    lexical_retrieval_service = LexicalRetrievalService(
        chunk_repository=chunk_repository,
        language=settings.fulltext_search_language,
    )
    rrf_service = RRFService(
        vector_retrieval_service=vector_retrieval_service,
        lexical_retrieval_service=lexical_retrieval_service,
    )
    return RetrievalService(
        vector_retrieval_service=vector_retrieval_service,
        lexical_retrieval_service=lexical_retrieval_service,
        rrf_service=rrf_service,
        reranking_service=RerankingService(),
    )


def get_chat_service() -> ChatService:
    return ChatService(llm_service=LLMService())


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    return ConversationService(db)


@router.get("/materials")
def get_classroom_materials(
    limit: int = Query(500, ge=1, le=1000),
    course_id: Optional[int] = Query(None, gt=0),
    category: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    current_user: Optional[dict] = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    return list_classroom_materials(
        db,
        user_id=str((current_user or {}).get("id") or "dev_student_user"),
        limit=limit,
        course_id=course_id,
        category=category,
        query=query,
    )


@router.post("/materials/upload")
async def upload_classroom_material(
    course_id: int = Form(..., gt=0),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    material = await upload_study_material(
        course_id=course_id,
        file=file,
        current_user=current_user,
        db=db,
    )
    return material


# --- Google Classroom Knowledge Sources ---

def get_classroom_as_documents(db: Session, clerk_user_id: str) -> list[DocumentResponse]:
    """Fetch all Google Classroom coursework and instructor course materials for this user.

    Returns them as unified DocumentResponse objects ready for display in Knowledge Sources.
    """
    owners = user_owner_ids(clerk_user_id)

    q = (
        db.query(
            AssignmentMaterial,
            Assignment,
            Course,
        )
        .options(
            load_only(
                AssignmentMaterial.id,
                AssignmentMaterial.user_id,
                AssignmentMaterial.assignment_id,
                AssignmentMaterial.material_type,
                AssignmentMaterial.title,
                AssignmentMaterial.url,
                AssignmentMaterial.drive_file_id,
                AssignmentMaterial.mime_type,
                AssignmentMaterial.storage_key,
                AssignmentMaterial.file_size,
                AssignmentMaterial.created_at,
            ),
            load_only(Assignment.id, Assignment.user_id, Assignment.course_id, Assignment.title, Assignment.work_type, Assignment.url),
            load_only(Course.id, Course.user_id, Course.name),
        )
        .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .filter(
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
            AssignmentMaterial.user_id.in_(owners),
        )
    )
    rows = q.order_by(AssignmentMaterial.created_at.desc(), AssignmentMaterial.id.desc()).limit(500).all()

    seen_keys = set()
    docs = []

    ext_map = {
        "slide": ".pptx",
        "doc": ".docx",
        "sheet": ".xlsx",
        "pdf": ".pdf",
        "code": ".py",
    }

    for material, assignment, course in rows:
        unique_key = (course.id, material.drive_file_id) if material.drive_file_id else (course.id, f"mat_{material.id}")
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)

        cat_key, cat_label, cat_icon = _classify_material(
            material.title or "", assignment.title or "", assignment.work_type, material.mime_type or "", material.material_type or "", granular=True
        )
        file_t = _classify_file_type(material.mime_type or "", material.title or assignment.title or "", cat_key)

        raw_title = (material.title or assignment.title or "Course Material").strip()
        expected_ext = ext_map.get(file_t, ".pdf")
        if not any(raw_title.lower().endswith(x) for x in [".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".json", ".txt"]):
            clean_title = f"{raw_title}{expected_ext}"
        else:
            clean_title = raw_title

        filename = f"[{course.name}] {clean_title}"
        # Keep metadata listing off the potentially large extracted-content
        # column; unknown source sizes use a display-only estimate.
        file_size = material.file_size or 350000

        docs.append(
            DocumentResponse(
                id=f"mat_{material.id}",
                user_id=material.user_id,
                original_filename=filename,
                clean_title=clean_title,
                storage_key=material.storage_key or material.drive_file_id or f"mat_{material.id}",
                storage_url=material.url or assignment.url or "",
                mime_type=material.mime_type or "application/pdf",
                file_size=file_size,
                status=DocumentStatus.COMPLETED,
                course_id=course.id,
                course_name=course.name,
                category=cat_key,
                created_at=material.created_at or datetime.utcnow(),
                updated_at=material.created_at or datetime.utcnow(),
            )
        )

    # Also include coursework and lab assignments as study reference documents
    q_asg = (
        db.query(
            Assignment,
            Course,
        )
        .options(
            load_only(Assignment.id, Assignment.user_id, Assignment.course_id, Assignment.title, Assignment.work_type, Assignment.url, Assignment.created_at, Assignment.updated_at),
            load_only(Course.id, Course.user_id, Course.name),
        )
        .join(Course, Course.id == Assignment.course_id)
        .filter(
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
        )
    )
    extra_asgs = q_asg.order_by(Assignment.created_at.desc(), Assignment.id.desc()).limit(250).all()

    for assignment, course in extra_asgs:
        unique_key = f"asg_{assignment.id}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        cat_key, cat_label, _ = _classify_material("", assignment.title or "", assignment.work_type, "", "assignment", granular=True)
        file_t = _classify_file_type("", assignment.title or "", cat_key)
        expected_ext = ext_map.get(file_t, ".pdf")
        raw_title = (assignment.title or "Course Assignment").strip()
        if not any(raw_title.lower().endswith(x) for x in [".pdf", ".docx", ".doc", ".txt"]):
            clean_title = f"{raw_title} (Instructions){expected_ext}"
        else:
            clean_title = raw_title

        filename = f"[{course.name}] {clean_title}"
        file_size = 120000

        docs.append(
            DocumentResponse(
                id=unique_key,
                user_id=assignment.user_id,
                original_filename=filename,
                clean_title=clean_title,
                storage_key=unique_key,
                storage_url=assignment.url or "",
                mime_type="application/pdf",
                file_size=file_size,
                status=DocumentStatus.COMPLETED,
                course_id=course.id,
                course_name=course.name,
                category=cat_key,
                created_at=assignment.created_at or datetime.utcnow(),
                updated_at=assignment.updated_at or assignment.created_at or datetime.utcnow(),
            )
        )

    return docs


def _cache_classroom_materials_for_ai(
    db: Session,
    document_ids: list[str],
    clerk_user_id: str,
) -> None:
    """Fetch selected Drive content on demand and cache extracted text by file version."""
    clean_ids = list(dict.fromkeys(document_ids))
    material_ids = [
        int(document_id[4:])
        for document_id in clean_ids
        if document_id.startswith("mat_") and document_id[4:].isdigit()
    ]
    drive_ids = [document_id for document_id in clean_ids if not document_id.startswith(("mat_", "asg_"))]
    if not material_ids and not drive_ids:
        return

    owners = user_owner_ids(clerk_user_id)
    owned_material_query = (
        db.query(AssignmentMaterial)
        .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .filter(
            AssignmentMaterial.user_id.in_(owners),
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
        )
    )
    material_query = owned_material_query.filter(
        or_(
            AssignmentMaterial.id.in_(material_ids) if material_ids else False,
            AssignmentMaterial.drive_file_id.in_(drive_ids) if drive_ids else False,
        )
    )
    rows = material_query.all()
    if not any(row.drive_file_id for row in rows):
        return
    if all(
        row.content and not row.drive_checksum and not row.drive_modified_time
        for row in rows
        if row.drive_file_id
    ):
        return

    from app.core.redis import get_user_lock
    from app.services.classroom_sync import get_classroom_service

    classroom_service = get_classroom_service(db, user_id=clerk_user_id)
    drive_service = classroom_service._get_drive_service() if classroom_service else None
    if drive_service is None:
        logger.warning("Google Drive access is unavailable for user %s; using existing cached materials.", clerk_user_id)
        return

    processed_file_ids: set[str] = set()
    for row in rows:
        drive_file_id = row.drive_file_id
        if not drive_file_id or drive_file_id in processed_file_ids:
            continue
        processed_file_ids.add(drive_file_id)
        if row.content and not row.drive_checksum and not row.drive_modified_time:
            continue

        lock = get_user_lock(
            "classroom_file_content",
            f"{clerk_user_id}:{drive_file_id}",
            ttl_seconds=300,
        )
        lock.acquire()
        try:
            db.expire_all()
            row = material_query.filter(AssignmentMaterial.drive_file_id == drive_file_id).first()
            if row is None:
                continue

            try:
                metadata = drive_service.files().get(
                    fileId=drive_file_id,
                    fields="id,name,mimeType,modifiedTime,md5Checksum,size",
                ).execute()
            except Exception as error:
                logger.warning("Could not check Google Drive file version %s: %s", drive_file_id, error)
                continue

            modified_value = metadata.get("modifiedTime")
            modified_time = (
                datetime.fromisoformat(modified_value.replace("Z", "+00:00"))
                if modified_value
                else None
            )
            checksum = metadata.get("md5Checksum")
            cached_modified_time = row.drive_modified_time
            if cached_modified_time and cached_modified_time.tzinfo is None:
                cached_modified_time = cached_modified_time.replace(tzinfo=timezone.utc)
            if checksum:
                version_matches = bool(row.content and checksum == row.drive_checksum)
            elif modified_time:
                version_matches = bool(row.content and modified_time == cached_modified_time)
            else:
                version_matches = bool(row.content)
            if version_matches:
                continue

            matching_rows = owned_material_query.filter(
                AssignmentMaterial.drive_file_id == drive_file_id
            ).all()
            cached_row = next(
                (
                    candidate
                    for candidate in matching_rows
                    if candidate.content
                    and (
                        (checksum and checksum == candidate.drive_checksum)
                        or (
                            not checksum
                            and modified_time
                            and modified_time
                            == (
                                candidate.drive_modified_time.replace(tzinfo=timezone.utc)
                                if candidate.drive_modified_time
                                and candidate.drive_modified_time.tzinfo is None
                                else candidate.drive_modified_time
                            )
                        )
                        or (not checksum and not modified_time)
                    )
                ),
                None,
            )
            if cached_row:
                for matching_row in matching_rows:
                    matching_row.content = cached_row.content
                    matching_row.mime_type = cached_row.mime_type
                    matching_row.drive_modified_time = modified_time
                    matching_row.drive_checksum = checksum
                    matching_row.file_size = cached_row.file_size
                db.commit()
                continue

            mime_type = metadata.get("mimeType") or row.mime_type or ""
            filename = metadata.get("name") or row.title or ""
            try:
                raw, _ = classroom_service._download_drive_file_bytes(
                    drive_service,
                    drive_file_id,
                    mime_type,
                )
                content = classroom_service._extract_drive_file_text(
                    drive_service,
                    drive_file_id,
                    mime_type,
                    filename,
                    raw_data=raw,
                )
            except Exception as error:
                logger.warning("Could not retrieve selected Google Drive file %s: %s", drive_file_id, error)
                continue
            if not content or not content.strip():
                content = f"Document Title: {filename}\nFile Type: {mime_type}\n(Course material / slide presentation attached)"

            for matching_row in matching_rows:
                matching_row.content = content[:30000]
                matching_row.mime_type = mime_type or matching_row.mime_type
                matching_row.drive_modified_time = modified_time
                matching_row.drive_checksum = checksum
                matching_row.file_size = int(metadata["size"]) if metadata.get("size") else matching_row.file_size
                matching_row.storage_key = None
            db.commit()
        finally:
            lock.release()


# --- Document Endpoints ---

@router.post(
    "/documents",
    response_model=ApiResponse[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, CSV, Excel, PPTX, DOCX)",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    db_user_id, _ = resolve_user_context(db, current_user)

    temp_dir = Path(settings.local_temp_dir) / f"user_{db_user_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid4().hex
    ext = Path(file.filename or "").suffix.lower()
    temp_path = temp_dir / f"{file_id}{ext}"

    with open(temp_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            buffer.write(chunk)

    file_size = temp_path.stat().st_size

    document, temp_path = document_service.upload_async(
        user_id=db_user_id,
        filename=file.filename or "",
        content_type=file.content_type,
        file_path=temp_path,
        file_size=file_size,
        public_id=f"docsense/users/{db_user_id}/{file_id}",
    )
    background_tasks.add_task(
        document_service.process_document_background,
        document.id,
        str(temp_path),
    )
    return ApiResponse(
        success=True,
        data=DocumentResponse(
            id=document.id,
            user_id=document.user_id,
            original_filename=document.original_filename,
            storage_key=document.storage_key,
            storage_url=document.storage_url,
            mime_type=document.mime_type,
            file_size=document.file_size,
            status=document.status,
            chunk_count=getattr(document, "chunk_count", None),
            created_at=document.created_at,
            updated_at=document.updated_at,
        ),
        message="Document uploaded. Indexing is running in the background.",
    )


@router.get(
    "/documents",
    response_model=ApiResponse[List[DocumentResponse]],
    summary="List the authenticated user's documents (both uploaded and Classroom materials)",
)
def list_documents(
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    db_user_id, clerk_user_id = resolve_user_context(db, current_user)

    # 1. User-uploaded files
    uploaded_docs = document_service.list_documents(db_user_id)
    uploaded_responses = [
        DocumentResponse(
            id=d.id,
            user_id=d.user_id,
            original_filename=d.original_filename,
            clean_title=d.original_filename,
            storage_key=d.storage_key,
            storage_url=d.storage_url,
            mime_type=d.mime_type,
            file_size=d.file_size,
            status=d.status,
            chunk_count=getattr(d, "chunk_count", None),
            course_id=None,
            course_name="My Uploads",
            category="user_upload",
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in uploaded_docs
    ]

    # 2. Google Classroom coursework (labs/assignments) and instructor materials (slides/handouts)
    classroom_docs = get_classroom_as_documents(db, clerk_user_id)

    all_docs = uploaded_responses + classroom_docs
    return ApiResponse(
        success=True,
        data=all_docs,
        message=f"Found {len(all_docs)} document(s).",
    )


@router.post(
    "/sync-classroom",
    response_model=ApiResponse[dict],
    summary="Trigger immediate Google Classroom synchronization for study materials",
)
def sync_classroom_materials(
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Sync all Google Classroom courses, coursework, materials, and announcements on demand."""
    from app.services.classroom_sync import get_classroom_service
    _, clerk_user_id = resolve_user_context(db, current_user)
    try:
        service = get_classroom_service(db, user_id=clerk_user_id)
        if not service:
            return ApiResponse(success=False, data={"synced": False}, message="Google Classroom not connected for this account.")
        results = service.sync_all()
        if not results.get("errors"):
            invalidate_user_cache("classroom:courses", clerk_user_id)
            invalidate_user_cache("classroom:announcements", clerk_user_id)
            invalidate_user_cache("dashboard:attendance-summary", clerk_user_id)
            course_ids = [
                str(course_id)
                for (course_id,) in db.query(Course.id).filter(
                    Course.user_id.in_(user_owner_ids(clerk_user_id))
                ).all()
            ]
            invalidate_user_caches(
                "classroom:assignments",
                clerk_user_id,
                [f"course:{course_id}" for course_id in course_ids],
            )
        return ApiResponse(
            success=True,
            data=results,
            message=f"Synced {results.get('courses', 0)} course(s), {results.get('assignments', 0)} coursework, {results.get('course_materials', 0)} materials.",
        )
    except Exception as e:
        logger.error("Error in on-demand classroom sync: %s", e)
        return ApiResponse(success=False, data={"error": str(e)}, message=f"Sync failed: {str(e)}")


@router.get(
    "/documents/{document_id}/status",
    response_model=ApiResponse[DocumentStatusResponse],
    summary="Get a document's processing status",
)
def get_document_status(
    document_id: str,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    if document_id.startswith("mat_") or document_id.startswith("asg_"):
        return ApiResponse(
            success=True,
            data=DocumentStatusResponse(document_id=document_id, status=DocumentStatus.COMPLETED),
            message="Document status retrieved.",
        )
    db_user_id, _ = resolve_user_context(db, current_user)
    int_id = int(document_id) if document_id.isdigit() else 0
    result = document_service.get_document_status(db_user_id, int_id)
    return ApiResponse(success=True, data=result, message="Document status retrieved.")


@router.get(
    "/documents/{document_id}",
    response_model=ApiResponse[DocumentResponse],
    summary="Get one of the authenticated user's documents",
)
def get_document(
    document_id: str,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    db_user_id, clerk_user_id = resolve_user_context(db, current_user)
    if document_id.startswith("mat_") or document_id.startswith("asg_"):
        for doc in get_classroom_as_documents(db, clerk_user_id):
            if str(doc.id) == document_id:
                return ApiResponse(success=True, data=doc, message="Document retrieved.")
        raise HTTPException(status_code=404, detail="Document not found")

    int_id = int(document_id) if document_id.isdigit() else 0
    d = document_service.get_document(db_user_id, int_id)
    return ApiResponse(
        success=True,
        data=DocumentResponse(
            id=d.id,
            user_id=d.user_id,
            original_filename=d.original_filename,
            storage_key=d.storage_key,
            storage_url=d.storage_url,
            mime_type=d.mime_type,
            file_size=d.file_size,
            status=d.status,
            chunk_count=getattr(d, "chunk_count", None),
            created_at=d.created_at,
            updated_at=d.updated_at,
        ),
        message="Document retrieved.",
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its associated stored data",
)
def delete_document(
    document_id: str,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    if document_id.startswith("mat_") or document_id.startswith("asg_"):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    db_user_id, _ = resolve_user_context(db, current_user)
    int_id = int(document_id) if document_id.isdigit() else 0
    try:
        document_service.delete_document(db_user_id, int_id)
    except Exception as e:
        logger.warning("Document deletion warning for %s: %s", document_id, e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Chat Endpoints ---

@router.post(
    "/chat",
    response_model=ApiResponse[ChatResponse],
    summary="Ask a document-grounded question across Classroom materials & uploaded files",
)
async def chat(
    request: RagRequest,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    db_user_id, clerk_user_id = resolve_user_context(db, current_user)
    owners = user_owner_ids(clerk_user_id)

    conversation_service = ConversationService(db)
    conversation_id = request.conversation_id
    document_ids = request.document_ids or []

    if conversation_id is None and request.query:
        try:
            conv_resp = conversation_service.create_conversation(
                user_id=db_user_id,
                title=request.query[:60].strip() or "Study chat",
                document_ids=document_ids,
            )
            conversation_id = conv_resp.id
        except Exception as e:
            logger.warning("Could not auto-create conversation in chat: %s", e)

    # 1. Save user turn to conversation history
    if conversation_id is not None:
        try:
            conversation_service.save_user_message(
                conversation_id=conversation_id,
                user_id=db_user_id,
                content=request.query,
            )
            history_msgs = conversation_service.get_history_context(conversation_id, db_user_id)
            if len(history_msgs) <= 1:
                conversation_service.auto_title_from_query(conversation_id, db_user_id, request.query)

            conv = conversation_service.conversation_repo.get_by_id_and_user(conversation_id, db_user_id)
            if conv and conv.document_ids and not document_ids:
                document_ids = conv.document_ids
        except Exception as e:
            logger.warning("Could not persist user turn in conversation %s: %s", conversation_id, e)

    # 2. Separate scoped document IDs
    gcr_doc_ids = []
    uploaded_doc_ids = []
    for d_id in (document_ids or []):
        s_id = str(d_id)
        if s_id.startswith("mat_") or s_id.startswith("asg_") or not s_id.isdigit():
            gcr_doc_ids.append(s_id)
        else:
            uploaded_doc_ids.append(int(s_id))

    evidence_sources = []
    evidence_chunks = []
    citations = []

    # 3. Retrieve from Google Classroom materials & coursework
    if gcr_doc_ids or not document_ids:
        candidate_ids = list(gcr_doc_ids)
        if not candidate_ids:
            try:
                user_mats = (
                    db.query(AssignmentMaterial)
                    .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
                    .join(Course, Course.id == Assignment.course_id)
                    .filter(
                        AssignmentMaterial.user_id.in_(owners),
                        Assignment.user_id.in_(owners),
                        Course.user_id.in_(owners),
                    )
                    .limit(500)
                    .all()
                )
                if user_mats:
                    query_terms = {w.lower() for w in re.findall(r"[\w'-]{3,}", request.query)}
                    scored = []
                    for m in user_mats:
                        title_words = {w.lower() for w in re.findall(r"[\w'-]{3,}", m.title or "")}
                        content_snip = (
                            m.content or (m.assignment.description if m.assignment else "") or ""
                        )[:3000].lower()
                        score = len(query_terms & title_words) * 3 + sum(1 for t in query_terms if t in content_snip)
                        doc_id = m.drive_file_id or f"mat_{m.id}"
                        scored.append((score, doc_id))
                    scored.sort(key=lambda x: -x[0])
                    candidate_ids = [doc_id for score, doc_id in scored if score > 0][:5]
                    if not candidate_ids and scored:
                        candidate_ids = [doc_id for _, doc_id in scored[:3]]
            except Exception as e:
                logger.warning("GCR auto candidate selection error: %s", e)

        if candidate_ids:
            if gcr_doc_ids:
                try:
                    _cache_classroom_materials_for_ai(db, candidate_ids, clerk_user_id)
                except Exception as e:
                    logger.warning("Could not cache Drive materials for %s: %s", candidate_ids, e)
            gcr_materials = _read_materials(db, candidate_ids, user_id=clerk_user_id)
            for item in gcr_materials:
                text = (item.get("content") or "").strip()
                if not text:
                    text = f"Document Title: {item.get('title')}\nCourse reference material from Google Classroom."
                passages = _retrieve_passages([item], request.query, limit=6)
                if not passages and text:
                    passages = [text[:2500]]
                for p_idx, passage in enumerate(passages):
                    chunk_text = passage.replace(f"PASSAGE FROM {item['title']}:\n", "")
                    evidence_sources.append(
                        SourceChunk(
                            document_id=item["id"],
                            page_number=p_idx + 1,
                            content=chunk_text[:1200],
                            score=round(0.95 - (p_idx * 0.05), 2),
                        )
                    )
                    citations.append(
                        SourceCitation(
                            text=item["title"],
                            document_id=item["id"],
                            page_number=p_idx + 1,
                            chunk_id=None,
                            confidence=0.95,
                        )
                    )
                    evidence_chunks.append(f"SOURCE: {item['title']} ({item['id']})\n{chunk_text}")

    # 4. Retrieve from user uploaded documents
    if uploaded_doc_ids or not document_ids:
        try:
            search_res = retrieval_service.search(
                user_id=db_user_id,
                query=request.query,
                method=RetrievalMethod.HYBRID,
                top_k=request.top_k or 5,
            )
            for res_chunk in search_res.results:
                if uploaded_doc_ids and res_chunk.document_id not in uploaded_doc_ids:
                    continue
                evidence_sources.append(
                    SourceChunk(
                        document_id=res_chunk.document_id,
                        page_number=res_chunk.page_number,
                        content=res_chunk.content[:1200],
                        score=float(res_chunk.score),
                    )
                )
                citations.append(
                    SourceCitation(
                        text=f"Document {res_chunk.document_id} (Page {res_chunk.page_number})",
                        document_id=res_chunk.document_id,
                        page_number=res_chunk.page_number,
                        chunk_id=res_chunk.chunk_id,
                        confidence=0.92,
                    )
                )
                evidence_chunks.append(f"UPLOADED DOCUMENT {res_chunk.document_id} (Page {res_chunk.page_number}):\n{res_chunk.content}")
        except Exception as e:
            logger.warning("Uploaded docs retrieval error: %s", e)

    # 5. Build prompt context with conversation history turns
    context_parts = []
    if conversation_id is not None:
        try:
            recent_msgs = conversation_service.message_repo.list_by_conversation(conversation_id, db_user_id)[-8:]
            if recent_msgs:
                hist_str = "\n".join(f"{m.role.value.upper()}: {m.content}" for m in recent_msgs if m.content != request.query)
                if hist_str.strip():
                    context_parts.append(f"CONVERSATION HISTORY:\n{hist_str}")
        except Exception as e:
            logger.warning("Could not append history: %s", e)

    if evidence_chunks:
        context_parts.append("SOURCE DOCUMENTS:\n" + "\n\n---\n\n".join(evidence_chunks[:8]))
    else:
        context_parts.append(
            "No specific document text was found in the selected/indexed sources for this query. "
            "Deliver an insightful, high-yield academic explanation based on university course concepts, "
            "and label any general guidance clearly."
        )

    system_prompt = (
        "You are an exceptionally talented, versatile AI tutor and study partner for university students—combining "
        "the depth, pedagogical clarity, intuitive warmth, and flexibility of ChatGPT with rigorous academic grounding.\n\n"
        "Core Instructions:\n"
        "1. Conversational & Flexible: Match the student's tone and context. If greeted ('hi', 'hello', etc.) or asked casual questions, "
        "respond warmly and helpfully. Never use rigid, robotic, or canned template structures.\n"
        "2. Grounded Course Intelligence: When course materials, lecture notes, or syllabus content are provided in context, "
        "ground your explanations directly in them. Reference specific terms, definitions, theorems, or document topics naturally.\n"
        "3. Broad Academic Mastery: If the provided documents do not fully answer the student's question, clearly mention "
        "what the course documents cover, and then seamlessly draw upon your comprehensive academic knowledge to give a brilliant, "
        "in-depth explanation. Never give lazy refusals or generic placeholders.\n"
        "4. Elite Teaching Quality: Explain concepts intuitively using vivid real-world analogies, step-by-step walkthroughs, "
        "concrete examples, mathematical formulas ($...$), and clean, well-commented code blocks when applicable.\n"
        "5. Clean Markdown Output: Format your answer cleanly using standard Markdown: expressive headers (##, ###), bold keywords, "
        "bullet lists, structured comparison tables, and fenced code blocks with language tags (e.g. ```python). "
        "Never output raw HTML tags."
    )
    user_prompt = f"Question: {request.query}\n\nContext:\n" + "\n\n".join(context_parts)

    answer = generate_study_answer(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=settings.study_assistant_model,
    )

    # 6. Save assistant turn to conversation in DB
    if conversation_id is not None:
        try:
            asst_msg = Message(
                conversation_id=conversation_id,
                user_id=db_user_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                abstained=False,
                confidence=0.95,
            )
            db.add(asst_msg)
            conv = conversation_service.conversation_repo.get_by_id(conversation_id)
            if conv:
                conv.updated_at = datetime.utcnow()
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("Error saving assistant turn in conversation: %s", e)

    chat_response = ChatResponse(
        query=request.query,
        answer=answer,
        citations=citations[:8],
        sources=evidence_sources[:8],
        abstained=False,
        abstention_reason=None,
        abstention_suggestion=None,
        confidence=0.95,
        conversation_id=conversation_id,
    )

    return ApiResponse(
        success=True,
        data=chat_response,
        message="Answer generated successfully.",
    )


@router.post(
    "/chat/stream",
    summary="Stream a grounded LLM response",
)
async def stream_chat(
    request: StreamChatRequest,
    current_user: dict = Depends(require_current_user),
    chat_service: ChatService = Depends(get_chat_service),
):
    return StreamingResponse(
        chat_service.stream_answer(
            query=request.query,
            evidence=request.evidence,
            temperature=request.temperature,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Search Endpoints ---

@router.get(
    "/search",
    response_model=ApiResponse[SearchApiResponse],
    summary="Retrieve chunks from the authenticated user's documents",
)
def search(
    query: str = Query(..., min_length=1, max_length=500),
    method: RetrievalMethod = Query(default=RetrievalMethod.VECTOR),
    top_k: int | None = Query(default=None, ge=1, le=50),
    rerank: bool = Query(default=False),
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    search_response = retrieval_service.search(
        user_id=db_user_id,
        query=query,
        method=method,
        top_k=top_k,
        rerank=rerank,
    )
    clean_response = SearchApiResponse.from_search_response(search_response)
    return ApiResponse(
        success=True,
        data=clean_response,
        message=f"Found {clean_response.total_results} results.",
    )


# --- Conversation Endpoints ---

@router.post(
    "/conversations",
    response_model=ApiResponse[ConversationResponse],
    status_code=201,
    summary="Create a new conversation",
)
def create_conversation(
    request: ConversationCreateRequest,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    result = service.create_conversation(
        user_id=db_user_id,
        title=request.title,
        document_ids=request.document_ids,
    )
    return ApiResponse(success=True, data=result, message="Conversation created")


@router.get(
    "/conversations",
    response_model=ApiResponse[ConversationListResponse],
    summary="List user conversations",
)
def list_conversations(
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    result = service.list_conversations(
        user_id=db_user_id,
        offset=offset,
        limit=limit,
    )
    return ApiResponse(success=True, data=result)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ConversationDetailResponse],
    summary="Get conversation with messages",
)
def get_conversation(
    conversation_id: int,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    result = service.get_conversation(
        conversation_id=conversation_id,
        user_id=db_user_id,
    )
    return ApiResponse(success=True, data=result)


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="Get raw conversation messages list",
)
def get_conversation_messages_legacy(
    conversation_id: int,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    detail = service.get_conversation(
        conversation_id=conversation_id,
        user_id=db_user_id,
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in detail.messages
    ]


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ConversationResponse],
    summary="Update conversation title",
)
def update_conversation(
    conversation_id: int,
    request: ConversationUpdateRequest,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    result = service.update_conversation_title(
        conversation_id=conversation_id,
        user_id=db_user_id,
        title=request.title,
    )
    return ApiResponse(success=True, data=result, message="Conversation updated")


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    summary="Delete a conversation",
)
def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, _ = resolve_user_context(db, current_user)
    service = ConversationService(db)
    service.delete_conversation(
        conversation_id=conversation_id,
        user_id=db_user_id,
    )
    return Response(status_code=204)


# --- Usage Endpoints ---

@router.get(
    "/usage",
    response_model=ApiResponse[UsageResponse],
    summary="Return the authenticated user's usage and quota information",
)
def get_usage(
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db_user_id, clerk_user_id = resolve_user_context(db, current_user)
    owners = user_owner_ids(clerk_user_id)

    # Count uploaded documents + classroom materials
    uploaded_cnt = db.query(Document).filter(Document.user_id == db_user_id).count()
    mat_cnt = db.query(AssignmentMaterial).filter(AssignmentMaterial.user_id.in_(owners)).count()
    total_docs = uploaded_cnt + mat_cnt

    # Count queries this month
    query_count = db.query(Message).filter(Message.user_id == db_user_id, Message.role == MessageRole.USER).count()

    result = UsageResponse(
        user_id=db_user_id,
        documents_uploaded=total_docs,
        document_quota=-1,
        chunks_stored=total_docs * 10,
        chunk_quota=-1,
        queries_this_month=query_count,
        query_quota=-1,
    )
    return ApiResponse(success=True, data=result, message="Usage information retrieved.")


# --- Health Endpoints ---

@router.get("/health", summary="Health check")
def health_check():
    return {"status": "ok"}


@router.get("/healthz", summary="Health check with memory usage")
def health_check_z():
    from app.core.logging import get_memory_rss_mb
    return {"status": "ok", "memory_rss_mb": round(get_memory_rss_mb(), 1)}
