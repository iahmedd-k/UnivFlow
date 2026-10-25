from __future__ import annotations

import logging

from app.core.config import settings
from app.schemas.retrieval import ChunkResult
from app.services.retrieval_service import (
    LexicalRetrievalService,
    VectorRetrievalService,
)

logger = logging.getLogger(__name__)


class RRFService:
    """Fuses ranked results using Reciprocal Rank Fusion (RRF).

    RRF combines two or more ordered result lists by summing a contribution
    that depends only on each result's rank position::

        RRF(d) = sum over lists of 1 / (k + rank(d))

    Raw similarity / FTS scores are intentionally ignored; only rank order
    matters. ``chunk_id`` is used as the unique identity across lists, so a
    chunk appearing in both lists accumulates its RRF contributions while a
    chunk in only one list keeps just that list's contribution.
    """

    def __init__(
        self,
        vector_retrieval_service: VectorRetrievalService,
        lexical_retrieval_service: LexicalRetrievalService,
        k: int | None = None,
    ):
        self.vector_retrieval_service = vector_retrieval_service
        self.lexical_retrieval_service = lexical_retrieval_service
        self.k = k if k is not None else settings.rrf_k

    def search(
        self,
        user_id: int,
        query: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[ChunkResult]:
        """Run both retrievals for a user and fuse them with RRF.

        Ownership filtering is enforced by each underlying retrieval method.
        Optionally scope to specific documents via ``document_ids``.
        """
        vector_results = self.vector_retrieval_service.retrieve(user_id, query, top_k, document_ids)
        lexical_results = self.lexical_retrieval_service.retrieve(user_id, query, top_k, document_ids)

        fused = self.fuse(vector_results, lexical_results)

        logger.info(
            "Fused %d vector + %d lexical results into %d for user %s (k=%d, doc_ids=%s)",
            len(vector_results),
            len(lexical_results),
            len(fused),
            user_id,
            self.k,
            document_ids,
        )
        return fused

    def fuse(
        self,
        *ranked_lists: list[ChunkResult],
    ) -> list[ChunkResult]:
        """Merge arbitrary ranked result lists into a single deduplicated list.

        Each list is expected to be ordered from most to least relevant; the
        1-based position of an item in its list is its rank. Results are
        deduplicated by ``chunk_id`` and sorted by descending RRF score.
        """
        if self.k <= 0:
            raise ValueError("RRF constant k must be positive")

        aggregated: dict[int, dict] = {}

        for ranked_list in ranked_lists:
            for rank, result in enumerate(ranked_list, start=1):
                contribution = 1.0 / (self.k + rank)

                entry = aggregated.get(result.chunk_id)
                if entry is None:
                    aggregated[result.chunk_id] = {
                        "result": result,
                        "score": contribution,
                    }
                else:
                    entry["score"] += contribution

        fused = [
            entry["result"].model_copy(update={"score": entry["score"]})
            for entry in aggregated.values()
        ]
        fused.sort(key=lambda result: result.score, reverse=True)

        return fused
