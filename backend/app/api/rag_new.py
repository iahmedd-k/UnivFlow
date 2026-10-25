import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.rag import _classify_file_type, _classify_material, _read_materials, _retrieve_passages
from app.auth.clerk_auth import require_current_user
from app.auth.ownership import user_owner_ids
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Assignment, AssignmentMaterial, Course
from app.db.repositories.credentials import GoogleCredentialRepository
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


# --- Google Classroom Knowledge Sources ---

def get_classroom_as_documents(db: Session, clerk_user_id: str) -> list[DocumentResponse]:
    """Fetch all Google Classroom coursework and instructor course materials for this user.

    Returns them as unified DocumentResponse objects ready for display in Knowledge Sources.
    """
    from app.services.classroom_sync import get_classroom_service

    owners = user_owner_ids(clerk_user_id)

    # Check if credentials exist in GoogleCredentialRepository
    cred_repo = GoogleCredentialRepository(db)
    creds = cred_repo.get(clerk_user_id)
    if not creds:
        for owner in owners:
            creds = cred_repo.get(owner)
            if creds:
                break

    # If connected and DB has no materials yet, run a fast initial sync
    try:
        existing_count = db.query(AssignmentMaterial).filter(AssignmentMaterial.user_id.in_(owners)).count()
        if creds and existing_count == 0:
            service = get_classroom_service(db, user_id=clerk_user_id)
            if service:
                courses = service._get_all_courses()
                for c in courses[:12]:
                    service._sync_course(c, is_active=True)
                    service._sync_coursework(c["id"], since_date=datetime(1970, 1, 1, tzinfo=timezone.utc))
                    service._sync_coursework_materials(c["id"])
                    service._sync_announcements(c)
    except Exception as e:
        logger.warning("Classroom initial sync attempt in rag_new: %s", e)

    q = (
        db.query(AssignmentMaterial, Assignment, Course)
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
            material.title or "", assignment.title or "", assignment.work_type, material.mime_type or "", material.material_type or ""
        )
        file_t = _classify_file_type(material.mime_type or "", material.title or assignment.title or "", cat_key)

        raw_title = (material.title or assignment.title or "Course Material").strip()
        expected_ext = ext_map.get(file_t, ".pdf")
        if not any(raw_title.lower().endswith(x) for x in [".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".json", ".txt"]):
            clean_title = f"{raw_title}{expected_ext}"
        else:
            clean_title = raw_title

        filename = f"[{course.name}] {clean_title}"
        file_size = material.file_size or (len(material.content.encode("utf-8")) if material.content else 350000)

        docs.append(
            DocumentResponse(
                id=f"mat_{material.id}",
                user_id=material.user_id,
                original_filename=filename,
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

    # Also include assignments & lab tasks that have descriptions/instructions
    seen_assignment_ids = {m.assignment_id for m, _, _ in rows}
    q_asg = (
        db.query(Assignment, Course)
        .join(Course, Course.id == Assignment.course_id)
        .filter(
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
        )
    )
    if seen_assignment_ids:
        q_asg = q_asg.filter(Assignment.id.notin_(seen_assignment_ids))
    extra_asgs = q_asg.order_by(Assignment.created_at.desc(), Assignment.id.desc()).limit(150).all()

    for assignment, course in extra_asgs:
        unique_key = f"asg_{assignment.id}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        cat_key, cat_label, _ = _classify_material("", assignment.title or "", assignment.work_type, "", "assignment")
        file_t = _classify_file_type("", assignment.title or "", cat_key)
        expected_ext = ext_map.get(file_t, ".pdf")
        raw_title = (assignment.title or "Course Assignment").strip()
        if not any(raw_title.lower().endswith(x) for x in [".pdf", ".docx", ".doc", ".txt"]):
            clean_title = f"{raw_title} (Instructions){expected_ext}"
        else:
            clean_title = raw_title

        filename = f"[{course.name}] {clean_title}"
        file_size = len((assignment.description or "").encode("utf-8")) or 120000

        docs.append(
            DocumentResponse(
                id=unique_key,
                user_id=assignment.user_id,
                original_filename=filename,
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


# --- Document Endpoints ---

@router.post(
    "/documents",
    response_model=ApiResponse[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, CSV, Excel, PPTX, DOCX)",
)
async def upload_document(
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
    document = document_service._process(temp_path, document)
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
        message="Document uploaded and processed.",
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
            storage_key=d.storage_key,
            storage_url=d.storage_url,
            mime_type=d.mime_type,
            file_size=d.file_size,
            status=d.status,
            chunk_count=getattr(d, "chunk_count", None),
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
                        or_(AssignmentMaterial.content.isnot(None), Assignment.description.isnot(None)),
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
                        content_snip = (m.content or "")[:3000].lower()
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
            gcr_materials = _read_materials(db, candidate_ids, user_id=clerk_user_id)
            for item in gcr_materials:
                text = (item.get("content") or "").strip()
                if not text:
                    continue
                passages = _retrieve_passages([item], request.query, limit=3)
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
        "You are an expert academic tutor and university study assistant. "
        "Your goal is to help the student excel in their courses, master challenging concepts, "
        "solve academic problems, and prepare high-yield study materials (such as revision summaries, "
        "cheat sheets, exam prep guides, formula lists, code explanations, and practice questions).\n\n"
        "Key instructions:\n"
        "1. When source documents or syllabus content are provided in the context, ground your answers directly "
        "in those materials and cite specific topics, formulas, or methods from them.\n"
        "2. When asked to prepare study materials, deliver rigorous, well-organized, and thorough content "
        "with markdown headings, clear bullet points, mathematical notations ($...$), and code snippets.\n"
        "3. Answer questions directly, step-by-step, and in depth. Never refuse or give vague non-answers.\n"
        "4. If specific course materials do not cover a requested topic, clearly say so, then give a useful "
        "general academic explanation and label it as general knowledge rather than course-source content."
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
        document_quota=500,
        chunks_stored=total_docs * 10,
        chunk_quota=50000,
        queries_this_month=query_count,
        query_quota=1000,
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