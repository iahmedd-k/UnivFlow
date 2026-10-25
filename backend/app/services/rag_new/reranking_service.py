from __future__ import annotations

import abc
import logging
import time

import httpx

from app.core.config import settings
from app.schemas.retrieval import ChunkResult

logger = logging.getLogger(__name__)


class RerankingError(Exception):
    """Raised when cross-encoder reranking fails."""


class CrossEncoderProvider(abc.ABC):
    """Abstract base class for cross-encoder reranking providers."""

    @abc.abstractmethod
    def rerank(self, query: str, contents: list[str]) -> list[float]:
        """Score each ``(query, content)`` pair and return a relevance score per item."""
        ...


class HuggingFaceRerankingProvider(CrossEncoderProvider):
    """Reranking provider backed by the Hugging Face Inference API.

    Calls the HF reranking endpoint:
        POST https://api-inference.huggingface.co/models/{model}/rerank
    with ``{"query": ..., "documents": [...]}`` and returns one score per document.
    """

    def __init__(
        self,
        token: str,
        model: str,
        base_url: str = "https://api-inference.huggingface.co",
    ):
        self.token = token
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Fast timeout: 2s connect, 5s total — fail fast if unreachable
        self._client = httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0))

    @property
    def model_name(self) -> str:
        return self.model

    def rerank(self, query: str, contents: list[str]) -> list[float]:
        if not contents:
            return []

        url = f"{self.base_url}/models/{self.model}/rerank"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "documents": contents,
            "top_n": len(contents),
        }

        try:
            response = self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RerankingError(
                f"Hugging Face API returned status {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise RerankingError(
                f"Failed to connect to Hugging Face API: {exc}"
            ) from exc

        data = response.json()
        results = data.get("results", [])

        # Map results back to original document order using index
        scores = [0.0] * len(contents)
        for item in results:
            idx = item.get("index", 0)
            scores[idx] = item.get("score", 0.0)

        return scores


class ScoreBasedRerankingProvider(CrossEncoderProvider):
    """Fallback reranking provider that passes through existing retrieval scores.

    When the HF Inference API is unavailable or the model is not supported,
    this provider uses the original retrieval scores as rerank scores.
    """

    @property
    def model(self) -> str:
        return "score-based"

    @property
    def model_name(self) -> str:
        return "score-based"

    def rerank(self, query: str, contents: list[str]) -> list[float]:
        if not contents:
            return []
        # Return uniform scores so the original retrieval order is preserved
        return [1.0] * len(contents)


class RerankingService:
    """Reranks retrieval candidates with a cross-encoder model.

    Uses the Hugging Face Inference API by default. Falls back to
    score-based reranking if the HF API is unavailable.
    """

    def __init__(
        self,
        provider: CrossEncoderProvider | None = None,
    ):
        self._provider = provider

    @property
    def provider(self) -> CrossEncoderProvider:
        if self._provider is None:
            self._provider = self._build_default_provider()
        return self._provider

    @staticmethod
    def _build_default_provider() -> CrossEncoderProvider:
        if not settings.huggingface_token:
            logger.warning(
                "HUGGINGFACE_TOKEN not set, using score-based reranking fallback"
            )
            return ScoreBasedRerankingProvider()

        # Use the direct HF API URL for reranking (not the router URL)
        return HuggingFaceRerankingProvider(
            token=settings.huggingface_token,
            model=settings.reranker_model,
            base_url="https://api-inference.huggingface.co",
        )

    @property
    def max_results(self) -> int:
        return settings.reranker_max_results

    @property
    def min_score(self) -> float:
        return settings.min_rerank_score

    def rerank(
        self,
        query: str,
        candidates: list[ChunkResult],
        top_n: int | None = None,
    ) -> list[ChunkResult]:
        """Score candidates against the query and return the top-N by relevance.

        Candidates are expected to be already ownership-filtered by the
        retrieval layer; no additional user/document filtering is performed
        here. The original retrieval ``score`` is preserved on each result and
        a new ``rerank_score`` is attached.

        Any candidate scoring below ``min_rerank_score`` is dropped before
        truncation to ``top_n``.  If zero candidates survive, an empty list
        is returned (triggering abstention downstream).
        """
        if not candidates:
            return []

        top_n = self._resolve_top_n(top_n)

        t0 = time.perf_counter()
        contents = [candidate.content for candidate in candidates]

        try:
            scores = self.provider.rerank(query, contents)
        except RerankingError as exc:
            logger.warning(
                "Reranking provider failed (%s), switching permanently to score-based reranking",
                exc,
            )
            self._provider = ScoreBasedRerankingProvider()
            scores = self._provider.rerank(query, contents)

        if len(scores) != len(candidates):
            raise RerankingError(
                f"Expected {len(candidates)} rerank scores, got {len(scores)}"
            )

        reranked = [
            candidate.model_copy(update={"rerank_score": score})
            for candidate, score in zip(candidates, scores)
        ]
        reranked.sort(key=lambda item: item.rerank_score, reverse=True)

        before_count = len(reranked)
        reranked = [c for c in reranked if c.rerank_score >= self.min_score]
        dropped = before_count - len(reranked)

        if dropped:
            logger.info(
                "Rerank threshold %.3f dropped %d/%d candidates",
                self.min_score,
                dropped,
                before_count,
            )

        logger.info(
            "Reranked %d candidates with %s in %.3fs (returning top %d, "
            "min_score=%.3f, dropped=%d)",
            before_count,
            settings.reranker_model,
            time.perf_counter() - t0,
            top_n,
            self.min_score,
            dropped,
        )
        return reranked[:top_n]

    def _resolve_top_n(self, top_n: int | None) -> int:
        if top_n is None:
            return self.max_results
        return max(1, min(top_n, self.max_results))
