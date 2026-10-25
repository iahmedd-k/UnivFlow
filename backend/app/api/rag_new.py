from fastapi import APIRouter, Depends, UploadFile, File, status, Query, HTTPException
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from typing import Optional, List

from app.auth.clerk_auth import get_current_user_optional, require_current_user
from app.auth.access_gate import require_access_grant
from app.db.database import get_db
from app.core.config import settings
from app.services.rag_new.embedding_service import EmbeddingService
from app.services.rag_new.llm_service import LLMService
from app.services.rag_new.query_analysis_service import QueryAnalysisService
from app.services.rag_new.chat_service import ChatService
from app.services.rag_new.rag_service import RAGService
from app.services.rag_new.reranking_service import RerankingService
from app.services.rag_new.retrieval_service import (
    LexicalRetrievalService,
    RetrievalMethod,
    RetrievalService,
    VectorRetrievalService,
)
from app.services.rag_new.rrf_service import RRFService
from app.services.rag_new.document_service import DocumentService
from app.services.rag_new.chunking_service import ChunkingService
from app.services.rag_new.pdf_parser_service import PdfParserService
from app.services.rag_new.spreadsheet_parser_service import SpreadsheetParserService
from app.services.rag_new.ppt_parser_service import PptParserService
from app.services.rag_new.docx_parser_service import DocxParserService
from app.services.rag_new.storage_service import StorageService
from app.services.rag_new.conversation_service import ConversationService
from app.services.rag_new.usage_service import UsageService
from app.repositories.document_repository import DocumentRepository
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.schemas.rag_new.document import DocumentResponse, DocumentStatusResponse
from app.schemas.rag_new.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
)
from app.schemas.rag_new.chat import StreamChatRequest
from app.schemas.rag_new.rag import ChatResponse, RagRequest
from app.schemas.rag_new.retrieval import SearchApiResponse
from app.schemas.rag_new.usage import UsageResponse
from app.schemas.rag_new.response import ApiResponse
from uuid import uuid4
from pathlib import Path

router = APIRouter(prefix="/rag", tags=["RAG"])

# --- Dependencies ---

def get_current_user_id(current_user: dict = Depends(require_current_user)) -> str:
    return current_user.get("id", "dev_student_user")

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

def get_rag_service(db: Session = Depends(get_db)) -> RAGService:
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
    retrieval_service = RetrievalService(
        vector_retrieval_service=vector_retrieval_service,
        lexical_retrieval_service=lexical_retrieval_service,
        rrf_service=rrf_service,
        reranking_service=RerankingService(),
    )

    llm_service = LLMService()
    chat_service = ChatService(llm_service=llm_service)
    query_analysis_service = QueryAnalysisService(llm_service=llm_service)

    return RAGService(
        query_analysis_service=query_analysis_service,
        retrieval_service=retrieval_service,
        rrf_service=rrf_service,
        chat_service=chat_service,
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

def get_usage_service(db: Session = Depends(get_db)) -> UsageService:
    return UsageService(db)

def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    return ConversationService(db)

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
    document_service: DocumentService = Depends(get_document_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1  # Default dev user ID for database
    
    temp_dir = Path(settings.local_temp_dir) / f"user_{user_id}"
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
        user_id=user_id,
        filename=file.filename or "",
        content_type=file.content_type,
        file_path=temp_path,
        file_size=file_size,
        public_id=f"docsense/users/{user_id}/{file_id}",
    )
    document = document_service._process(temp_path, document)
    return ApiResponse(
        success=True,
        data=document,
        message="Document uploaded and processed.",
    )

@router.get(
    "/documents",
    response_model=ApiResponse[List[DocumentResponse]],
    summary="List the authenticated user's documents",
)
def list_documents(
    current_user: dict = Depends(require_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    results = document_service.list_documents(user_id)
    return ApiResponse(
        success=True,
        data=results,
        message=f"Found {len(results)} document(s).",
    )

@router.get(
    "/documents/{document_id}/status",
    response_model=ApiResponse[DocumentStatusResponse],
    summary="Get a document's processing status",
)
def get_document_status(
    document_id: int,
    current_user: dict = Depends(require_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    result = document_service.get_document_status(user_id, document_id)
    return ApiResponse(success=True, data=result, message="Document status retrieved.")

@router.get(
    "/documents/{document_id}",
    response_model=ApiResponse[DocumentResponse],
    summary="Get one of the authenticated user's documents",
)
def get_document(
    document_id: int,
    current_user: dict = Depends(require_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    result = document_service.get_document(user_id, document_id)
    return ApiResponse(success=True, data=result, message="Document retrieved.")

@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its associated stored data",
)
def delete_document(
    document_id: int,
    current_user: dict = Depends(require_current_user),
    document_service: DocumentService = Depends(get_document_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    document_service.delete_document(user_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Chat Endpoints ---

@router.post(
    "/chat",
    response_model=ApiResponse[ChatResponse],
    summary="Ask a document-grounded question",
    description=(
        "Lean RAG pipeline: query analysis → hybrid retrieval → "
        "answer generation. 2 LLM calls max. Optionally pass a "
        "conversation_id to persist the conversation."
    ),
)
def chat(
    request: RagRequest,
    current_user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
    rag_service: RAGService = Depends(get_rag_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1

    usage_service = UsageService(db)
    if usage_service._count_queries(user_id) >= 7:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demo query quota reached (7/7 queries used). You have reached the maximum allowed queries for this demo session.",
        )

    conversation_service = ConversationService(db)

    conversation_id = request.conversation_id
    document_ids = request.document_ids

    if conversation_id is not None:
        conversation_service.save_user_message(
            conversation_id=conversation_id,
            user_id=user_id,
            content=request.query,
        )

        messages = conversation_service.get_history_context(
            conversation_id, user_id,
        )

        is_first = len(messages) <= 1
        if is_first:
            conversation_service.auto_title_from_query(
                conversation_id, user_id, request.query,
            )

        conversation = conversation_service.conversation_repo.get_by_id_and_user(
            conversation_id, user_id,
        )
        if conversation and conversation.document_ids:
            document_ids = conversation.document_ids

    rag_response = rag_service.answer(
        user_id=user_id,
        query=request.query,
        top_k=request.top_k,
        document_ids=document_ids,
    )

    if conversation_id is not None:
        conversation_service.save_assistant_message(
            conversation_id=conversation_id,
            user_id=user_id,
            rag_response=rag_response,
        )

    chat_response = ChatResponse.from_rag_response(rag_response)

    if chat_response.abstained:
        message = chat_response.abstention_reason or "Unable to answer based on available documents."
    else:
        message = "Answer generated successfully."

    return ApiResponse(
        success=True,
        data=chat_response,
        message=message,
    )

@router.post(
    "/chat/stream",
    summary="Stream a grounded LLM response",
    description=(
        "Streams the grounded answer text using Server-Sent Events (SSE). "
        "Requires evidence chunks from a previous RAG call. "
        "Each chunk is formatted as: data: {\"event\": \"chunk\", \"data\": \"...\"}\\n\\n"
    ),
    responses={
        200: {
            "description": "SSE stream of grounded answer chunks",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_chat(
    request: StreamChatRequest,
    current_user: dict = Depends(require_current_user),
    chat_service: ChatService = Depends(get_chat_service),
):
    """Stream the grounded answer as SSE chunks."""
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
    method: RetrievalMethod = Query(
        default=RetrievalMethod.VECTOR,
        description="Retrieval strategy: vector (semantic), lexical (full-text), or hybrid (RRF)",
    ),
    top_k: int | None = Query(
        default=None,
        ge=1,
        le=settings.retrieval_max_top_k,
        description="Number of results to return (defaults to server config)",
    ),
    rerank: bool = Query(
        default=False,
        description="Re-score candidates with the cross-encoder reranker",
    ),
    current_user: dict = Depends(require_current_user),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    search_response = retrieval_service.search(
        user_id=user_id,
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
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    service = ConversationService(db)
    result = service.create_conversation(
        user_id=user_id,
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
    limit: int = Query(default=20, ge=1, le=100),
):
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    service = ConversationService(db)
    result = service.list_conversations(
        user_id=user_id,
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
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    service = ConversationService(db)
    result = service.get_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
    )
    return ApiResponse(success=True, data=result)

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
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    service = ConversationService(db)
    result = service.update_conversation_title(
        conversation_id=conversation_id,
        user_id=user_id,
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
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    service = ConversationService(db)
    service.delete_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
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
    user_id = current_user.get("id", "dev_student_user")
    if isinstance(user_id, str) and user_id.startswith("dev_"):
        user_id = 1
    usage_service = UsageService(db)
    result = usage_service.get_usage(user_id)
    return ApiResponse(success=True, data=result, message="Usage information retrieved.")

# --- Health Endpoints ---

@router.get("/health", summary="Health check")
def health_check():
    return {"status": "ok"}

@router.get("/healthz", summary="Health check with memory usage")
def health_check_z():
    from app.core.logging import get_memory_rss_mb
    return {"status": "ok", "memory_rss_mb": round(get_memory_rss_mb(), 1)}