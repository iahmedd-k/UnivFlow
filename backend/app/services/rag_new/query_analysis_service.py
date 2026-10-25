from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.schemas.query_analysis import (
    QUERY_INTENT_COMPARISON,
    QUERY_INTENT_LISTING,
    QUERY_INTENT_OPEN_ENDED,
    QUERY_INTENT_QA,
    QUERY_INTENT_SUMMARIZATION,
    VALID_INTENTS,
    QueryAnalysis,
)
from app.services.llm_service import LLMError, LLMService

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are a search query analyst for a document retrieval system. Given a user \
question, decide whether the question needs additional retrieval queries.

- EXPANSION: when the question can be answered using several different \
phrasings or keywords, return up to 3 paraphrased query variants that would \
each retrieve complementary evidence.
- DECOMPOSITION: when the question asks about two or more distinct facts, \
split it into up to 3 independent sub-questions, each answerable on its own.

Use neither when a single faithful query is enough. Respond with STRICT JSON \
only and no extra text, using this exact shape:
{
  "needs_expansion": <true or false>,
  "expanded_queries": ["<variant 1>", "<variant 2>"],
  "needs_decomposition": <true or false>,
  "sub_queries": ["<sub-question 1>", "<sub-question 2>"],
  "query_intent": "<intent>",
  "rationale": "<brief string>"
}

Rules:
- Do not fabricate expansion or decomposition when not required; return empty lists.
- Keep every variant/sub-question faithful to the original question.
- Return searchable queries, never a question addressed to an assistant.

query_intent must be one of:
- "summarization": user wants a summary, overview, or general understanding of the document
- "qa": user asks a specific factual question with a clear answer
- "comparison": user compares multiple things (methods, results, approaches)
- "listing": user wants a list of items, findings, recommendations, etc.
- "open_ended": general exploration, no clear intent above
"""


class QueryAnalysisService:
    """Analyzes a query and produces expansion/decomposition variants (Flow 3).

    The LLM is only consulted to decide whether expansion or decomposition is
    needed. The service always converges to a usable analysis (falling back to
    the original query alone) so downstream retrieval never fails.
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

    @property
    def max_expansion_queries(self) -> int:
        return settings.query_analysis_max_expansion

    @property
    def max_sub_queries(self) -> int:
        return settings.query_analysis_max_sub_queries

    def analyze(self, query: str) -> QueryAnalysis:
        """Return a query analysis for ``query``.

        LLM failures are non-fatal: the original query alone is used so the
        composed pipeline remains available even when analysis is unavailable.
        """
        try:
            t0 = time.perf_counter()
            data = self.llm_service.complete_json(ANALYSIS_SYSTEM_PROMPT, query)
            logger.info("LLM query_analysis: %.3fs", time.perf_counter() - t0)
        except LLMError as exc:
            logger.warning("Query analysis LLM call failed: %s", exc)
            return QueryAnalysis(
                original_query=query,
                rationale="Query analysis LLM unavailable; using the original query alone.",
            )
        except Exception as exc:  # defensive: never break the pipeline
            logger.warning("Query analysis failed unexpectedly: %s", exc)
            return QueryAnalysis(
                original_query=query,
                rationale="Query analysis failed; using the original query alone.",
            )

        return self._parse(data, query)

    def _parse(self, data: dict, query: str) -> QueryAnalysis:
        expanded = self._clean_list(
            data.get("expanded_queries"), self.max_expansion_queries
        )
        sub_queries = self._clean_list(
            data.get("sub_queries"), self.max_sub_queries
        )

        if data.get("needs_expansion") is False:
            expanded = []
        if data.get("needs_decomposition") is False:
            sub_queries = []

        # Extract and validate query intent
        raw_intent = str(data.get("query_intent") or "").strip().lower()
        query_intent = raw_intent if raw_intent in VALID_INTENTS else QUERY_INTENT_OPEN_ENDED

        return QueryAnalysis(
            original_query=query,
            query_intent=query_intent,
            expanded_queries=expanded,
            sub_queries=sub_queries,
            rationale=str(data.get("rationale") or ""),
        )

    @staticmethod
    def _clean_list(values: object, limit: int) -> list[str]:
        cleaned: list[str] = []
        if isinstance(values, list):
            for item in values:
                text = str(item).strip()
                if text and text not in cleaned and len(cleaned) < limit:
                    cleaned.append(text)
        return cleaned