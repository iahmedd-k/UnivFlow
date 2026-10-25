from __future__ import annotations

import abc
import json
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


class LLMError(Exception):
    """Raised when an LLM chat completion fails."""


class ChatProvider(abc.ABC):
    """Abstract base class for chat completion providers."""

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
    ) -> str:
        """Return the assistant message content for the given chat messages.

        ``messages`` follows the OpenAI chat format: a list of ``{"role": ...,
        "content": ...}`` dicts.
        """
        ...


class GroqChatProvider(ChatProvider):
    """OpenAI-compatible chat provider backed by the Groq API.

    Calls::

        POST {base_url}/chat/completions

    with the OpenAI-compatible payload and returns the assistant content. The
    transport mirrors the HuggingFace embedding provider (httpx, bearer auth).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=60.0)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers)

                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("retry-after", RETRY_BASE_DELAY * attempt)
                    )
                    logger.warning(
                        "Groq rate-limited (attempt %d/%d), retrying in %.1fs",
                        attempt,
                        MAX_RETRIES,
                        retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429:
                    retry_after = float(
                        exc.response.headers.get("retry-after", RETRY_BASE_DELAY * attempt)
                    )
                    logger.warning(
                        "Groq rate-limited (attempt %d/%d), retrying in %.1fs",
                        attempt,
                        MAX_RETRIES,
                        retry_after,
                    )
                    time.sleep(retry_after)
                    continue
                raise LLMError(
                    f"Groq API returned status {exc.response.status_code}: "
                    f"{exc.response.text}"
                ) from exc
            except httpx.RequestError as exc:
                last_exc = exc
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    "Groq connection error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue

            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(
                    f"Unexpected Groq response format: {type(data).__name__}"
                ) from exc

        raise LLMError(
            f"Groq API failed after {MAX_RETRIES} attempts"
        ) from last_exc


class LLMService:
    """High-level chat completion service for structured LLM tasks.

    Exposes ``complete_json`` so graders and query refineries can request
    structured output. The concrete provider is built lazily on first use.
    """

    def __init__(
        self,
        provider: ChatProvider | None = None,
    ):
        self._provider = provider

    @property
    def provider(self) -> ChatProvider:
        if self._provider is None:
            self._provider = self._build_default_provider()
        return self._provider

    @staticmethod
    def _build_default_provider() -> ChatProvider:
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is required for the LLM provider")
        if not settings.groq_chat_model:
            raise LLMError("GROQ_CHAT_MODEL is required for the LLM provider")
        return GroqChatProvider(
            api_key=settings.groq_api_key,
            model=settings.groq_chat_model,
            base_url=settings.groq_base_url,
        )

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> str:
        """Run a single-turn chat completion and return the raw content."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self.provider.chat(messages, temperature=temperature)

    def complete_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> dict:
        """Run a chat completion and parse the response as a JSON object.

        Tolerates markdown-fenced JSON blocks. Raises LLMError when the
        response cannot be parsed.
        """
        content = self.complete(system, user, temperature=temperature)
        return self._parse_json(content)

    @staticmethod
    def _parse_json(content: str) -> dict:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise LLMError(
                f"Expected LLM JSON object, got {type(data).__name__}"
            )
        return data