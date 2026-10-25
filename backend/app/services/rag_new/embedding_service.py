from __future__ import annotations

import abc
import logging
import math
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


class EmbeddingProvider(abc.ABC):
    """Abstract base class for embedding providers."""

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider using sentence-transformers."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        logger.info("Loading local embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)
        logger.info("Local embedding model loaded: %s", model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by Hugging Face Inference & Router APIs."""

    def __init__(
        self,
        token: str,
        model: str,
        base_url: str = "https://api-inference.huggingface.co",
    ):
        self.token = token
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=120.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        endpoints = []
        if self.base_url.endswith("/v1") or "/v1" in self.base_url:
            endpoints.append((
                f"{self.base_url}/embeddings",
                {"model": self.model, "input": texts},
            ))
            endpoints.append((
                f"https://router.huggingface.co/hf-inference/models/{self.model}",
                {"inputs": texts},
            ))
            endpoints.append((
                f"https://api-inference.huggingface.co/models/{self.model}",
                {"inputs": texts},
            ))
        else:
            endpoints.append((
                f"{self.base_url}/models/{self.model}",
                {"inputs": texts},
            ))
            endpoints.append((
                f"https://router.huggingface.co/hf-inference/models/{self.model}",
                {"inputs": texts},
            ))
            endpoints.append((
                f"https://api-inference.huggingface.co/models/{self.model}",
                {"inputs": texts},
            ))

        last_error = None
        for url, payload in endpoints:
            try:
                response = self._client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    return _parse_embeddings_response(response.json())
                last_error = f"Endpoint {url} returned HTTP {response.status_code}: {response.text}"
            except Exception as exc:
                last_error = f"Endpoint {url} error: {exc}"

        raise EmbeddingError(f"Hugging Face API failed across endpoints: {last_error}")


class SimpleHashEmbeddingProvider(EmbeddingProvider):
    """Lightweight, zero-dependency embedding provider using feature hashing.

    No model download, no external API, no heavy RAM usage.  Deterministic:
    the same text always produces the same vector.  Good enough for demo /
    local development on memory-constrained hosts (Render free tier).
    """

    def __init__(self, dimension: int):
        self.dimension = dimension

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in text.lower().split() if t]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Per-document term frequencies.
        term_freqs: list[dict[str, int]] = []
        doc_freq: dict[str, int] = {}

        for text in texts:
            tokens = self._tokenize(text)
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            term_freqs.append(tf)
            for tok in tf:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        num_docs = len(texts)

        vectors: list[list[float]] = []
        for tf in term_freqs:
            vec = [0.0] * self.dimension
            total_terms = sum(tf.values()) or 1
            for tok, count in tf.items():
                idx = abs(hash(tok)) % self.dimension
                # TF * IDF weighting (IDF computed across this batch).
                idf = math.log1p(num_docs / (1 + doc_freq.get(tok, 1)))
                vec[idx] += (count / total_terms) * idf

            # L2 normalize.
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])

        return vectors


class EmbeddingService:
    """High-level service for generating text embeddings.

    The concrete provider is built lazily on first use so the service can be
    instantiated (and injected across the application) without requiring API
    credentials at startup.
    """

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
    ):
        self._provider = provider

    @property
    def provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = self._build_default_provider()
        return self._provider

    @staticmethod
    def _build_default_provider() -> EmbeddingProvider:
        provider_name = settings.embedding_provider.lower()

        if provider_name == "local":
            try:
                return LocalEmbeddingProvider(model_name=settings.embedding_model)
            except Exception as exc:
                if settings.huggingface_token:
                    logger.warning(
                        "Local embedding provider failed to load (%s), falling back to Hugging Face Cloud API",
                        exc,
                    )
                    return HuggingFaceEmbeddingProvider(
                        token=settings.huggingface_token,
                        model=settings.embedding_model,
                        base_url=settings.huggingface_inference_url,
                    )
                raise EmbeddingError(f"Local embedding provider failed: {exc}") from exc

        if provider_name == "huggingface":
            if not settings.huggingface_token:
                raise EmbeddingError(
                    "HUGGINGFACE_TOKEN is required for the huggingface embedding provider"
                )
            return HuggingFaceEmbeddingProvider(
                token=settings.huggingface_token,
                model=settings.embedding_model,
                base_url=settings.huggingface_inference_url,
            )

        raise EmbeddingError(
            f"Unknown embedding provider: {provider_name}"
        )

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Rejects any text that is empty or whitespace-only as a safety net
        (the chunking layer is the primary guard for size).

        Raises EmbeddingError on failure.
        """
        if not texts:
            return []

        original_count = len(texts)
        filtered = [t for t in texts if t.strip()]

        if not filtered:
            raise EmbeddingError(
                "All texts rejected: no non-empty texts to embed"
            )

        if len(filtered) < original_count:
            logger.warning(
                "Filtered %d empty/whitespace texts before embedding "
                "(%d remaining)",
                original_count - len(filtered),
                len(filtered),
            )

        logger.info(
            "Generating embeddings for %d texts using %s/%s",
            len(filtered),
            settings.embedding_provider,
            settings.embedding_model,
        )

        t0 = time.perf_counter()
        try:
            embeddings = self.provider.embed(filtered)
        except Exception as exc:
            if isinstance(self.provider, LocalEmbeddingProvider) and settings.huggingface_token:
                logger.warning("Local embedding failed (%s), switching to Hugging Face Cloud API", exc)
                self._provider = None
                self._provider = HuggingFaceEmbeddingProvider(
                    token=settings.huggingface_token,
                    model=settings.embedding_model,
                    base_url=settings.huggingface_inference_url,
                )
                embeddings = self._provider.embed(filtered)
            elif isinstance(self.provider, HuggingFaceEmbeddingProvider):
                try:
                    logger.warning("Hugging Face API failed (%s), switching to local embedding model", exc)
                    self._provider = None
                    self._provider = LocalEmbeddingProvider(model_name=settings.embedding_model)
                    embeddings = self._provider.embed(filtered)
                except Exception as local_exc:
                    logger.warning(
                        "Both cloud and local embedding providers failed (%s, %s), "
                        "falling back to lightweight hash embeddings",
                        exc,
                        local_exc,
                    )
                    self._provider = None
                    self._provider = SimpleHashEmbeddingProvider(
                        dimension=settings.embedding_dimension
                    )
                    embeddings = self._provider.embed(filtered)
            else:
                logger.warning(
                    "Primary embedding provider failed (%s), falling back to "
                    "lightweight hash embeddings",
                    exc,
                )
                self._provider = None
                self._provider = SimpleHashEmbeddingProvider(
                    dimension=settings.embedding_dimension
                )
                embeddings = self._provider.embed(filtered)

        logger.info("Embedding generation: %.3fs", time.perf_counter() - t0)

        if len(embeddings) != len(filtered):
            raise EmbeddingError(
                f"Expected {len(filtered)} embeddings, got {len(embeddings)}"
            )

        logger.info("Successfully generated %d embeddings", len(embeddings))
        return embeddings

    @staticmethod
    def filter_texts(texts: list[str]) -> list[str]:
        """Filter out empty/whitespace-only texts to align with generate_embeddings."""
        return [t for t in texts if t.strip()]

    def generate_embedding(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        results = self.generate_embeddings([text])
        return results[0]


def _parse_embeddings_response(data) -> list[list[float]]:
    """Normalize Hugging Face responses to a flat list of vectors.

    The HF API can return:
    - A bare list of vectors ``[[...], [...]]`` for multiple inputs
    - A single flat vector ``[...]`` for a single input
    - An OpenAI-compatible dict ``{"data": [{"embedding": ...}]}``
    """
    if isinstance(data, list):
        if data and isinstance(data[0], (int, float)):
            return [data]
        return data

    if isinstance(data, dict) and "data" in data:
        items = sorted(data["data"], key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]

    raise EmbeddingError(
        f"Unexpected Hugging Face response format: {type(data).__name__}"
    )