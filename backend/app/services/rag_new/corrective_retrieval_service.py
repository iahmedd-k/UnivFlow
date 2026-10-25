from __future__ import annotations

import logging

from app.core.config import settings
from app.schemas.evidence import CorrectiveRetrievalResponse
from app.schemas.retrieval import ChunkResult
from app.services.evidence_grader_service import EvidenceGraderService
from app.services.query_refinement_service import QueryRefinementService
from app.services.retrieval_service import RetrievalMethod, RetrievalService

logger = logging.getLogger(__name__)


class CorrectiveRetrievalService:
    """FR-016 — Bounded corrective retrieval.

    The reranked evidence produced by the existing hybrid pipeline is graded by
    the evidence sufficiency grader (FR-015). When insufficient, the query is
    refined and the full pipeline (vector + lexical retrieval -> RRF ->
    cross-encoder reranking -> evidence grading) is re-run for a bounded number
    of attempts.

    The loop is always bounded: once the maximum number of attempts is reached
    an explicit insufficient-evidence result is returned so a downstream
    feature (FR-020) can abstain. Chunk provenance (page numbers, document,
    metadata) is never reconstructed here; it flows through untouched on the
    ``ChunkResult`` objects returned by the retrieval pipeline.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        evidence_grader_service: EvidenceGraderService,
        query_refinement_service: QueryRefinementService,
        max_attempts: int | None = None,
    ):
        self.retrieval_service = retrieval_service
        self.evidence_grader_service = evidence_grader_service
        self.query_refinement_service = query_refinement_service
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        if self._max_attempts is None:
            return max(0, settings.corrective_retrieval_max_attempts)
        return max(0, self._max_attempts)

    def search(
        self,
        user_id: int,
        query: str,
        top_k: int | None = None,
        max_attempts: int | None = None,
        query_intent: str = "open_ended",
    ) -> CorrectiveRetrievalResponse:
        """Run bounded corrective retrieval for an authenticated user.

        Ownership filtering is enforced by the underlying retrieval pipeline;
        no additional user/document filtering is performed here.
        """
        resolved_attempts = (
            self.max_attempts if max_attempts is None else max(0, max_attempts)
        )

        corrective_queries: list[str] = []
        current_query = query
        attempts_used = 0

        evidence = self._retrieve(user_id, current_query, top_k)
        verdict = self.evidence_grader_service.grade(
            current_query, evidence, query_intent=query_intent
        )

        while not verdict.sufficient and attempts_used < resolved_attempts:
            refined = self.query_refinement_service.refine(query, verdict)

            if not refined.query or refined.query == current_query:
                logger.info(
                    "Corrective refinement stalled; stopping after %d attempt(s)",
                    attempts_used,
                )
                break

            current_query = refined.query
            corrective_queries.append(current_query)
            attempts_used += 1

            new_evidence = self._retrieve(user_id, current_query, top_k)
            evidence = self._merge_evidence(evidence, new_evidence, top_k)
            verdict = self.evidence_grader_service.grade(
                current_query, evidence, query_intent=query_intent
            )

        logger.info(
            "Corrective retrieval for user %s: sufficient=%s after %d corrective "
            "attempt(s) (max=%d)",
            user_id,
            verdict.sufficient,
            attempts_used,
            resolved_attempts,
        )

        return CorrectiveRetrievalResponse(
            original_query=query,
            final_query=current_query,
            sufficient=verdict.sufficient,
            evidence=evidence,
            verdict=verdict,
            attempts_used=attempts_used,
            max_attempts=resolved_attempts,
            corrective_queries=corrective_queries,
        )

    def _retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int | None,
    ) -> list[ChunkResult]:
        """Reranked hybrid evidence via the existing retrieval pipeline."""
        response = self.retrieval_service.search(
            user_id=user_id,
            query=query,
            method=RetrievalMethod.HYBRID,
            top_k=top_k,
            rerank=True,
        )
        return response.results

    @staticmethod
    def _merge_evidence(
        existing: list[ChunkResult],
        new: list[ChunkResult],
        top_k: int | None = None,
    ) -> list[ChunkResult]:
        """Merge two evidence lists by chunk_id union, keeping highest score.

        Deduplicates by chunk_id, keeping the entry with the higher score.
        Preserves order: existing chunks first, then new ones not already present.
        Optionally truncates to top_k by score.
        """
        seen: dict[int, ChunkResult] = {}
        for chunk in existing:
            seen[chunk.chunk_id] = chunk
        for chunk in new:
            if chunk.chunk_id not in seen:
                seen[chunk.chunk_id] = chunk
            elif chunk.score > seen[chunk.chunk_id].score:
                seen[chunk.chunk_id] = chunk

        merged = list(seen.values())
        merged.sort(key=lambda c: c.score, reverse=True)

        if top_k is not None and top_k > 0:
            merged = merged[:top_k]

        return merged