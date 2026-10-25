from __future__ import annotations

import logging
import time

from app.schemas.evidence import EvidenceVerdict
from app.schemas.query_analysis import QueryAnalysis
from app.schemas.rag import RagResponse
from app.schemas.retrieval import ChunkResult
from app.services.chat_service import ChatService
from app.services.query_analysis_service import QueryAnalysisService
from app.services.retrieval_service import RetrievalMethod, RetrievalService
from app.services.rrf_service import RRFService

logger = logging.getLogger(__name__)


class RAGService:
    """Lean RAG pipeline — 2 LLM calls max.

    1. Query analysis (expand/decompose)       -- 1 LLM call
    2. Hybrid retrieval (vector + lexical + RRF) -- 0 LLM calls
    3. Answer generation                        -- 1 LLM call

    No evidence grading, no verification, no revision, no citation generation.
    The answer generation prompt handles grounding and formatting.
    """

    def __init__(
        self,
        query_analysis_service: QueryAnalysisService,
        retrieval_service: RetrievalService,
        rrf_service: RRFService,
        chat_service: ChatService,
    ):
        self.query_analysis_service = query_analysis_service
        self.retrieval_service = retrieval_service
        self.rrf_service = rrf_service
        self.chat_service = chat_service

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def answer(
        self,
        user_id: int,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
    ) -> RagResponse:
        """Run the lean pipeline and return a grounded response.

        When ``document_ids`` is provided, retrieval is scoped to those
        documents only.
        """
        t0 = time.perf_counter()

        # Step 1: Query analysis (1 LLM call)
        t_step = time.perf_counter()
        analysis = self.query_analysis_service.analyze(query)
        t_analysis = time.perf_counter() - t_step
        logger.info("RAG [user=%s] query_analysis: %.3fs (intent=%s)", user_id, t_analysis, analysis.query_intent)

        # Step 2: Retrieval (0 LLM calls)
        t_step = time.perf_counter()
        evidence = self._retrieve_merged(user_id, query, analysis, top_k, document_ids)
        t_retrieval = time.perf_counter() - t_step
        logger.info("RAG [user=%s] retrieval: %.3fs (%d chunks)", user_id, t_retrieval, len(evidence))

        # No evidence = abstain (no LLM call needed)
        if not evidence:
            verdict = EvidenceVerdict(
                sufficient=False,
                confidence_score=0.0,
                reason="No relevant documents found.",
                missing_information=["No evidence was found for the question."],
            )
            resp = self._abstain(
                query=query,
                analysis=analysis,
                evidence=evidence,
                verdict=verdict,
                reason="No relevant documents found. Please upload documents first.",
            )
            logger.info("RAG [user=%s] TOTAL (no evidence): %.3fs", user_id, time.perf_counter() - t0)
            return resp

        # Step 3: Answer generation (1 LLM call)
        t_step = time.perf_counter()
        answer = self.chat_service.generate_answer(query, evidence)
        t_answer = time.perf_counter() - t_step
        logger.info("RAG [user=%s] generate_answer: %.3fs", user_id, t_answer)

        # Build response
        verdict = EvidenceVerdict(
            sufficient=True,
            confidence_score=0.9,
            reason="Evidence retrieved and answer generated.",
            missing_information=[],
        )

        total = time.perf_counter() - t0
        logger.info(
            "RAG [user=%s] TOTAL: %.3fs (analysis=%.3fs, retrieval=%.3fs, answer=%.3fs)",
            user_id,
            total,
            t_analysis,
            t_retrieval,
            t_answer,
        )

        return RagResponse(
            query=query,
            query_analysis=analysis,
            evidence=evidence,
            verdict=verdict,
            answer=answer,
            citations=[],
            verification=None,
            abstained=False,
            corrective_queries=[],
            corrective_attempts=0,
            revision_attempts=0,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _retrieve_merged(
        self,
        user_id: int,
        query: str,
        analysis: QueryAnalysis,
        top_k: int | None,
        document_ids: list[int] | None,
    ) -> list[ChunkResult]:
        """Run hybrid retrieval per query and fuse with RRF."""
        retrieval_queries = self._retrieval_queries(query, analysis)

        lists: list[list[ChunkResult]] = []
        for q in retrieval_queries:
            response = self.retrieval_service.search(
                user_id=user_id,
                query=q,
                method=RetrievalMethod.HYBRID,
                top_k=top_k,
                rerank=True,
                document_ids=document_ids,
            )
            if response.results:
                lists.append(response.results)

        if not lists:
            return []
        if len(lists) == 1:
            return lists[0]
        return self.rrf_service.fuse(*lists)

    @staticmethod
    def _retrieval_queries(query: str, analysis: QueryAnalysis) -> list[str]:
        queries = [query]
        for extra in analysis.expanded_queries + analysis.sub_queries:
            extra = extra.strip()
            if extra and extra not in queries:
                queries.append(extra)
        return queries

    @staticmethod
    def _abstain(
        *,
        query: str,
        analysis: QueryAnalysis,
        evidence: list[ChunkResult],
        verdict: EvidenceVerdict,
        reason: str,
    ) -> RagResponse:
        """Build an abstention response."""
        return RagResponse(
            query=query,
            query_analysis=analysis,
            evidence=evidence,
            verdict=verdict,
            answer=None,
            citations=[],
            verification=None,
            abstained=True,
            abstention_reason=reason,
            abstention_suggestion="",
            corrective_queries=[],
            corrective_attempts=0,
            revision_attempts=0,
        )
