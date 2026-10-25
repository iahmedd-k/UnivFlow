from __future__ import annotations

import logging

from app.schemas.evidence import EvidenceVerdict, RefinedQuery
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

REFINEMENT_SYSTEM_PROMPT = """\
You are a search query refiner for a document retrieval system. Given the \
user's original question and the information the previous retrieval was \
missing, produce a refined search query that is likely to retrieve the \
missing information.

Respond with STRICT JSON only and no extra text, using this exact shape:
{
  "query": "<refined search query>",
  "rationale": "<brief string>"
}

Rules:
- The refined query must stay faithful to the user's original intent.
- Focus the query on the listed missing information.
- Return a concrete, searchable query (not a question to an assistant).
"""


class QueryRefinementService:
    """Generates a corrective search query from a failed grading pass.

    Bridges the FR-016 corrective loop with the existing retrieval pipeline:
    the refined query is fed back through vector + lexical retrieval, RRF, and
    reranking. When the verdict is already sufficient (or no missing
    information was reported) the original query is returned unchanged so the
    corrective loop always converges.
    """

    def __init__(
        self,
        llm_service: LLMService | None = None,
    ):
        self._llm_service = llm_service

    @property
    def llm_service(self) -> LLMService:
        if self._llm_service is None:
            self._llm_service = LLMService()
        return self._llm_service

    def refine(
        self,
        user_query: str,
        verdict: EvidenceVerdict,
    ) -> RefinedQuery:
        """Produce a refined query targeting the missing information."""
        if verdict.sufficient:
            return RefinedQuery(
                query=user_query,
                rationale="Evidence is already sufficient; no refinement needed.",
            )

        if not verdict.missing_information:
            return RefinedQuery(
                query=user_query,
                rationale=(
                    "No specific missing information reported; reusing the "
                    "original query."
                ),
            )

        user_prompt = self._build_prompt(user_query, verdict.missing_information)
        data = self.llm_service.complete_json(
            REFINEMENT_SYSTEM_PROMPT, user_prompt
        )

        query = str(data.get("query") or "").strip()
        if not query:
            logger.warning(
                "Query refiner returned an empty query; falling back to "
                "original query %r",
                user_query,
            )
            query = user_query

        return RefinedQuery(
            query=query,
            rationale=str(data.get("rationale") or ""),
        )

    @staticmethod
    def _build_prompt(
        user_query: str,
        missing_information: list[str],
    ) -> str:
        missing_lines = "\n".join(f"- {item}" for item in missing_information)
        return (
            f"Original question: {user_query}\n\n"
            f"Missing information from previous retrieval:\n"
            f"{missing_lines}"
        )