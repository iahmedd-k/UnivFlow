from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.models.user import User
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.schemas.chat import StreamChatRequest
from app.schemas.rag import ChatResponse, RagRequest
from app.schemas.response import ApiResponse
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.query_analysis_service import QueryAnalysisService
from app.services.rag_service import RAGService
from app.services.reranking_service import RerankingService
from app.services.retrieval_service import (
    LexicalRetrievalService,
    RetrievalService,
    VectorRetrievalService,
)
from app.services.rrf_service import RRFService
from app.services.usage_service import UsageService

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_service() -> ChatService:
    return ChatService(llm_service=LLMService())


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


@router.post(
    "",
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rag_service: RAGService = Depends(get_rag_service),
):
    usage_service = UsageService(db)
    if usage_service._count_queries(current_user.id) >= 7:
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
            user_id=current_user.id,
            content=request.query,
        )

        messages = conversation_service.get_history_context(
            conversation_id, current_user.id,
        )

        is_first = len(messages) <= 1
        if is_first:
            conversation_service.auto_title_from_query(
                conversation_id, current_user.id, request.query,
            )

        conversation = conversation_service.conversation_repo.get_by_id_and_user(
            conversation_id, current_user.id,
        )
        if conversation and conversation.document_ids:
            document_ids = conversation.document_ids

    rag_response = rag_service.answer(
        user_id=current_user.id,
        query=request.query,
        top_k=request.top_k,
        document_ids=document_ids,
    )

    if conversation_id is not None:
        conversation_service.save_assistant_message(
            conversation_id=conversation_id,
            user_id=current_user.id,
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
    "/stream",
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
    current_user: User = Depends(get_current_user),
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
