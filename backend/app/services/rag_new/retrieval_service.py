from __future__ import annotations

import enum
import logging
import time
from typing import TYPE_CHECKING

from app.core.config import settings
from app.repositories.document_chunk_repository import (
    DocumentChunkRepository,
    RetrievedChunk,
)
from app.schemas.retrieval import ChunkResult, SearchResponse
from app.services.embedding_service import EmbeddingService

if TYPE_CHECKING:
    from app.services.reranking_service import RerankingService
    from app.services.rrf_service import RRFService

logger = logging.getLogger(__name__)


class VectorRetrievalService:
    """Semantic retrieval over DocumentChunk embeddings using pgvector.

    The user query is embedded with the same provider/model used during
    ingestion (FR-009) and then matched against stored chunk embeddings using
    cosine similarity. Ownership filtering (``user_id``) is enforced inside the
    repository query.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunk_repository: DocumentChunkRepository,
    ):
        self.embedding_service = embedding_service
        self.chunk_repository = chunk_repository

    def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[ChunkResult]:
        t0 = time.perf_counter()
        query_vector = self.embedding_service.generate_embedding(query)
        logger.info("Vector retrieval embed: %.3fs", time.perf_counter() - t0)

        t0 = time.perf_counter()
        results = self.chunk_repository.search_by_embedding(
            user_id=user_id,
            query_vector=query_vector,
            top_k=top_k,
            document_ids=document_ids,
        )
        logger.info("Vector retrieval DB search: %.3fs (%d results)", time.perf_counter() - t0, len(results))

        return [
            self._to_result(chunk) for chunk in results
        ]

    @staticmethod
    def _to_result(chunk: RetrievedChunk) -> ChunkResult:
        return ChunkResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            page_numbers=chunk.page_numbers,
            content_type=chunk.content_type,
            metadata=chunk.metadata,
            score=chunk.score,
        )


class LexicalRetrievalService:
    """Full-text retrieval over DocumentChunk.content using PostgreSQL FTS.

    Uses a ``websearch_to_tsquery`` query and ``ts_rank`` ranking against the
    precomputed ``search_vector`` (see migration 0006). Ownership filtering
    (``user_id``) is enforced inside the repository query.
    """

    def __init__(
        self,
        chunk_repository: DocumentChunkRepository,
        language: str = "english",
    ):
        self.chunk_repository = chunk_repository
        self.language = language

    def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[ChunkResult]:
        t0 = time.perf_counter()
        results = self.chunk_repository.search_by_text(
            user_id=user_id,
            query=query,
            top_k=top_k,
            language=self.language,
            document_ids=document_ids,
        )
        logger.info("Lexical retrieval DB search: %.3fs (%d results)", time.perf_counter() - t0, len(results))

        return [
            self._to_result(chunk) for chunk in results
        ]

    @staticmethod
    def _to_result(chunk: RetrievedChunk) -> ChunkResult:
        return ChunkResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            page_numbers=chunk.page_numbers,
            content_type=chunk.content_type,
            metadata=chunk.metadata,
            score=chunk.score,
        )


class RetrievalMethod(str, enum.Enum):
    """Supported retrieval strategies exposed by the retrieval service."""

    VECTOR = "vector"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


class RetrievalService:
    """Orchestrates document retrieval for an authenticated user.

    Dispatches to the concrete vector (semantic), lexical (full-text), or
    hybrid (RRF-fused) retrieval strategy based on the requested ``method``.
    Results can optionally be re-scored by a cross-encoder reranker. Query
    expansion and evidence grading are intentionally not part of this feature.
    """

    def __init__(
        self,
        vector_retrieval_service: VectorRetrievalService,
        lexical_retrieval_service: LexicalRetrievalService,
        rrf_service: RRFService | None = None,
        reranking_service: RerankingService | None = None,
    ):
        self.vector_retrieval_service = vector_retrieval_service
        self.lexical_retrieval_service = lexical_retrieval_service
        self.rrf_service = rrf_service
        self.reranking_service = reranking_service

    @property
    def default_top_k(self) -> int:
        return settings.retrieval_default_top_k

    @property
    def max_top_k(self) -> int:
        return settings.retrieval_max_top_k

    def search(
        self,
        user_id: int,
        query: str,
        method: str,
        top_k: int | None = None,
        rerank: bool = False,
        document_ids: list[int] | None = None,
    ) -> SearchResponse:
        """Run a single-method retrieval and shape the response.

        When ``rerank`` is enabled, additional candidates are fetched and
        re-scored by the cross-encoder reranker before the final top-K is
        returned. Optionally scope to specific documents via ``document_ids``.
        """
        top_k = self._resolve_top_k(top_k)

        if rerank:
            results = self._search_with_reranking(user_id, query, method, top_k, document_ids)
        else:
            results = self._retrieve(user_id, query, method, top_k, document_ids)

        logger.info(
            "Retrieved %d results for user %s using method=%s doc_ids=%s",
            len(results),
            user_id,
            method,
            document_ids,
        )
        return SearchResponse(query=query, results=results)

    def _retrieve(
        self,
        user_id: int,
        query: str,
        method: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[ChunkResult]:
        if method == RetrievalMethod.LEXICAL:
            return self.lexical_retrieval_service.retrieve(user_id, query, top_k, document_ids)
        elif method == RetrievalMethod.VECTOR:
            return self.vector_retrieval_service.retrieve(user_id, query, top_k, document_ids)
        elif method == RetrievalMethod.HYBRID:
            if self.rrf_service is None:
                raise ValueError("Hybrid retrieval requires an RRF service")
            return self.rrf_service.search(user_id, query, top_k, document_ids)
        else:
            raise ValueError(f"Unsupported retrieval method: {method}")

    def _search_with_reranking(
        self,
        user_id: int,
        query: str,
        method: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[ChunkResult]:
        if self.reranking_service is None:
            raise ValueError("Reranking requires a reranking service")

        candidate_count = self._candidate_count_for_rerank(top_k)
        candidates = self._retrieve(user_id, query, method, candidate_count, document_ids)

        return self.reranking_service.rerank(query, candidates, top_n=top_k)

    def _candidate_count_for_rerank(self, top_k: int) -> int:
        count = top_k * settings.reranker_candidate_multiplier
        return max(1, min(count, settings.reranker_max_results))

    def _resolve_top_k(self, top_k: int | None) -> int:
        if top_k is None:
            return self.default_top_k
        return max(1, min(top_k, self.max_top_k))
