from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.models.user import User
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.schemas.response import ApiResponse
from app.schemas.retrieval import SearchApiResponse
from app.services.embedding_service import EmbeddingService
from app.services.reranking_service import RerankingService
from app.services.retrieval_service import (
    LexicalRetrievalService,
    RetrievalMethod,
    RetrievalService,
    VectorRetrievalService,
)
from app.services.rrf_service import RRFService

router = APIRouter(prefix="/search", tags=["search"])


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


@router.get(
    "",
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
    current_user: User = Depends(get_current_user),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    search_response = retrieval_service.search(
        user_id=current_user.id,
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
