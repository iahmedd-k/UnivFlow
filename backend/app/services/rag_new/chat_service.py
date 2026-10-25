from __future__ import annotations

import json
import logging
import re
import time
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestError, ServiceUnavailableError
from app.schemas.chat import (
    AbstentionRequest,
    AbstentionResponse,
    CitationMismatch,
    CitationRequest,
    CitationResponse,
    SourceCitation,
    VerificationRequest,
    VerificationResponse,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResultItem,
)
from app.schemas.evidence import EvidenceVerdict
from app.schemas.retrieval import ChunkResult
from app.services.llm_service import LLMError, LLMService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FR-018 — Citation Generation
# ---------------------------------------------------------------------------

CITATION_SYSTEM_PROMPT = """\
You are a citation generator for a document question-answering system. Given a \
user query, a generated answer, and evidence chunks from source documents, \
produce precise page/source citations.

For each claim or statement in the answer that is supported by evidence, \
create a citation linking it to the specific document and page.

Respond with STRICT JSON only and no extra text, using this exact shape:
{
  "citations": [
    {
      "text": "<exact text span from the answer>",
      "document_id": <int>,
      "page_number": <int>,
      "chunk_id": <int>,
      "confidence": <float 0.0 to 1.0>
    }
  ]
}

Rules:
- Each citation must reference a document_id, page_number, AND chunk_id that exist in the evidence.
- The "text" field must be an exact substring of the answer.
- confidence reflects how strongly the evidence supports that specific claim.
- Only cite claims that are actually supported by the evidence.
- Do NOT fabricate citations for claims not present in the evidence.
"""

# ---------------------------------------------------------------------------
# FR-019 — Verification
# ---------------------------------------------------------------------------

VERIFICATION_SYSTEM_PROMPT = """\
You are an answer and citation verification system for a document \
question-answering pipeline. Given a user query, a generated answer, \
evidence chunks, and their citation mappings, verify:

1. Whether the answer is fully supported by the evidence.
2. Whether each citation correctly references its claimed source.

Respond with STRICT JSON only and no extra text, using this exact shape:
{
  "supported": <true or false>,
  "citations_correct": <true or false>,
  "issues": [
    {
      "citation_text": "<the problematic citation text>",
      "claimed_document_id": <int>,
      "claimed_page": <int>,
      "issue": "<description of the mismatch>"
    }
  ],
  "explanation": "<brief explanation of the verification outcome>"
}

Rules:
- "supported" is false ONLY when the answer contains claims that are clearly fabricated or contradict the evidence.
- Minor paraphrasing or restating evidence in your own words is acceptable and should be marked as supported.
- "citations_correct" is false only when citations point to completely wrong documents or pages.
- Minor citation mismatches (e.g. off by one page) should be flagged in "issues" but should NOT cause citations_correct to be false.
- Be lenient: the goal is to catch genuinely wrong answers, not nitpick formatting.
"""

# ---------------------------------------------------------------------------
# FR-020 — Abstention
# ---------------------------------------------------------------------------

ABSTENTION_SYSTEM_PROMPT = """\
You are an abstention decision system for a document question-answering \
pipeline. Given a user query, retrieved evidence, an evidence sufficiency \
verdict, and an optional draft answer, decide whether the system should \
abstain from providing an answer.

Abstain when:
- The evidence is clearly insufficient to answer the query.
- The answer cannot be reliably supported by the available evidence.
- The confidence score is too low to be trustworthy.

Respond with STRICT JSON only and no extra text, using this exact shape:
{
  "abstain": <true or false>,
  "reason": "<clear reason for the decision>",
  "suggestion": "<optional suggestion for the user, e.g. rephrase>"
}

Rules:
- When abstaining, provide a clear, user-friendly reason.
- When not abstaining, explain why the evidence is sufficient.
- suggestion should help the user if they are being asked to rephrase.
"""

# ---------------------------------------------------------------------------
# Answer Revision (Flow 4)
# ---------------------------------------------------------------------------

REVISION_SYSTEM_PROMPT = """\
You are an answer reviser for a document question-answering pipeline. A \
previous answer was verified against its retrieved evidence and found to be \
unsupported, incorrectly cited, or both. Revise the answer so every claim is \
fully grounded in the provided evidence.

Respond with the revised answer text only; no JSON, no preamble.

Rules:
- Only use information present in the evidence chunks.
- If the evidence cannot support a claim, remove the claim instead of guessing.
- Keep the answer concise and faithful to the evidence.
- Do NOT include chunk IDs, document IDs, page numbers, or any internal \
reference markers like [1], 【1†L1-L2】, or (chunk_id=X).
- Write a clean, professional response — the citation system handles \
sources automatically.
"""

# ---------------------------------------------------------------------------
# Web Search Provider (FR-023)
# ---------------------------------------------------------------------------

_DDG_URL = "https://html.duckduckgo.com/html/"


class WebSearchProvider:
    """Minimal DuckDuckGo web search provider using httpx."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=15.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
        )

    def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[WebSearchResultItem]:
        """Perform a web search and return parsed results."""
        try:
            response = self._client.post(_DDG_URL, data={"q": query})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ServiceUnavailableError(
                f"Web search returned status {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(
                f"Web search request failed: {exc}"
            ) from exc

        return self._parse_results(response.text, max_results)

    def _parse_results(
        self,
        html: str,
        max_results: int,
    ) -> list[WebSearchResultItem]:
        """Extract results from the DuckDuckGo HTML page."""
        results: list[WebSearchResultItem] = []

        result_blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for rank, (url, title, snippet) in enumerate(result_blocks, start=1):
            if rank > max_results:
                break
            title_clean = re.sub(r"<.*?>", "", title).strip()
            snippet_clean = re.sub(r"<.*?>", "", snippet).strip()
            url_clean = self._clean_ddg_url(url)
            if title_clean and url_clean:
                results.append(
                    WebSearchResultItem(
                        title=title_clean,
                        url=url_clean,
                        snippet=snippet_clean,
                        rank=rank,
                    )
                )

        return results

    @staticmethod
    def _clean_ddg_url(url: str) -> str:
        """Extract the actual URL from DuckDuckGo's redirect wrapper."""
        match = re.search(r"uddg=([^&]+)", url)
        if match:
            from urllib.parse import unquote

            return unquote(match.group(1))
        return url.strip()


class WebSearchError(Exception):
    """Raised when a web search operation fails."""


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------


class ChatService:
    """Business logic for chat-related features (FR-018 through FR-023).

    Keeps all LLM orchestration, prompt construction, and web search logic
    out of the route handlers. The service is stateless and wired via
    dependency injection.
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

    # ------------------------------------------------------------------
    # FR-018 — Citations
    # ------------------------------------------------------------------

    def generate_citations(self, request: CitationRequest) -> CitationResponse:
        """Generate page/source citations for the grounded answer."""
        evidence_summary = self._format_evidence(request.evidence)
        user_prompt = (
            f"User query: {request.query}\n\n"
            f"Generated answer:\n{request.answer}\n\n"
            f"Evidence chunks:\n{evidence_summary}"
        )

        try:
            t0 = time.perf_counter()
            data = self.llm_service.complete_json(
                CITATION_SYSTEM_PROMPT,
                user_prompt,
            )
            logger.info("LLM citations: %.3fs", time.perf_counter() - t0)
        except LLMError as exc:
            raise ServiceUnavailableError(
                f"Citation generation failed: {exc}"
            ) from exc

        citations = self._parse_citations(data, request.evidence)

        return CitationResponse(
            query=request.query,
            answer=request.answer,
            citations=citations,
        )

    @staticmethod
    def _parse_citations(
        data: dict,
        evidence: list[ChunkResult],
    ) -> list[SourceCitation]:
        raw_citations = data.get("citations")
        if not isinstance(raw_citations, list):
            return []

        valid_ids = {c.chunk_id for c in evidence}
        valid_doc_pages = {
            (c.document_id, c.page_number) for c in evidence
        }

        citations: list[SourceCitation] = []
        dropped = 0
        for item in raw_citations:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            doc_id = item.get("document_id")
            page = item.get("page_number")
            chunk_id_raw = item.get("chunk_id")
            confidence = item.get("confidence")

            if not text or doc_id is None or page is None:
                continue

            doc_id_int = int(doc_id)
            page_int = int(page)

            if (doc_id_int, page_int) not in valid_doc_pages:
                dropped += 1
                logger.warning(
                    "Citation dropped: document_id=%d, page_number=%d not in "
                    "evidence set",
                    doc_id_int,
                    page_int,
                )
                continue

            chunk_id = chunk_id_raw
            if chunk_id is not None:
                try:
                    chunk_id = int(chunk_id)
                except (TypeError, ValueError):
                    dropped += 1
                    logger.warning(
                        "Citation dropped: chunk_id=%r is not a valid integer",
                        chunk_id_raw,
                    )
                    continue
                if chunk_id not in valid_ids:
                    dropped += 1
                    logger.warning(
                        "Citation dropped: chunk_id=%d not in evidence set",
                        chunk_id,
                    )
                    continue

            citations.append(
                SourceCitation(
                    text=text,
                    document_id=doc_id_int,
                    page_number=page_int,
                    chunk_id=chunk_id,
                    confidence=(
                        float(confidence) if confidence is not None else None
                    ),
                )
            )

        if dropped:
            logger.info(
                "Dropped %d fabricated citations; %d valid citations remaining",
                dropped,
                len(citations),
            )

        return citations

    # ------------------------------------------------------------------
    # FR-019 — Verification
    # ------------------------------------------------------------------

    def verify_answer(self, request: VerificationRequest) -> VerificationResponse:
        """Verify that the answer is supported by evidence and citations."""
        evidence_summary = self._format_evidence(request.evidence)
        user_prompt = (
            f"User query: {request.query}\n\n"
            f"Generated answer:\n{request.answer}\n\n"
            f"Evidence chunks:\n{evidence_summary}"
        )

        try:
            t0 = time.perf_counter()
            data = self.llm_service.complete_json(
                VERIFICATION_SYSTEM_PROMPT,
                user_prompt,
            )
            logger.info("LLM verification: %.3fs", time.perf_counter() - t0)
        except LLMError as exc:
            raise ServiceUnavailableError(
                f"Answer verification failed: {exc}"
            ) from exc

        return self._parse_verification(data)

    @staticmethod
    def _parse_verification(data: dict) -> VerificationResponse:
        supported = bool(data.get("supported", False))
        citations_correct = bool(data.get("citations_correct", True))
        explanation = str(data.get("explanation", ""))

        raw_issues = data.get("issues") or []
        issues: list[CitationMismatch] = []
        if isinstance(raw_issues, list):
            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                issues.append(
                    CitationMismatch(
                        citation_text=str(item.get("citation_text", "")),
                        claimed_document_id=int(
                            item.get("claimed_document_id", 0)
                        ),
                        claimed_page=int(item.get("claimed_page", 0)),
                        issue=str(item.get("issue", "")),
                    )
                )

        return VerificationResponse(
            supported=supported,
            citations_correct=citations_correct,
            issues=issues,
            explanation=explanation,
        )

    # ------------------------------------------------------------------
    # FR-020 — Abstention
    # ------------------------------------------------------------------

    def decide_abstention(self, request: AbstentionRequest) -> AbstentionResponse:
        """Decide whether to abstain from answering based on evidence."""
        evidence_summary = self._format_evidence(request.evidence)
        verdict_text = (
            f"sufficient={request.verdict.sufficient}, "
            f"confidence={request.verdict.confidence_score}, "
            f"reason={request.verdict.reason}"
        )

        parts = [
            f"User query: {request.query}",
            f"Evidence verdict: {verdict_text}",
        ]
        if request.verdict.missing_information:
            parts.append(
                f"Missing information: {', '.join(request.verdict.missing_information)}"
            )
        if request.evidence:
            parts.append(f"Evidence chunks:\n{evidence_summary}")
        if request.answer:
            parts.append(f"Draft answer:\n{request.answer}")

        user_prompt = "\n\n".join(parts)

        try:
            data = self.llm_service.complete_json(
                ABSTENTION_SYSTEM_PROMPT,
                user_prompt,
            )
        except LLMError as exc:
            raise ServiceUnavailableError(
                f"Abstention decision failed: {exc}"
            ) from exc

        return self._parse_abstention(data)

    @staticmethod
    def _parse_abstention(data: dict) -> AbstentionResponse:
        abstain = bool(data.get("abstain", True))
        reason = str(data.get("reason", "Insufficient evidence to provide an answer."))
        suggestion = str(data.get("suggestion", ""))

        return AbstentionResponse(
            abstain=abstain,
            reason=reason,
            suggestion=suggestion,
        )

    # ------------------------------------------------------------------
    # FR-021 — Streaming
    # ------------------------------------------------------------------

    async def stream_answer(
        self,
        query: str,
        evidence: list[ChunkResult],
        temperature: float = 0.0,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted streaming chunks from the LLM."""
        system_prompt = self._build_grounded_system_prompt()
        evidence_summary = self._format_evidence(evidence)
        user_prompt = (
            f"User query: {query}\n\n"
            f"Evidence chunks:\n{evidence_summary}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        provider = self.llm_service.provider

        if not hasattr(provider, "chat_stream"):
            # Fallback: non-streaming provider — yield the full response
            try:
                content = provider.chat(messages, temperature=temperature)
            except Exception as exc:
                yield f"data: {json.dumps({'event': 'error', 'data': str(exc)})}\n\n"
                return
            yield f"data: {json.dumps({'event': 'chunk', 'data': content})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'data': ''})}\n\n"
            return

        try:
            async for chunk in provider.chat_stream(messages, temperature=temperature):
                yield f"data: {json.dumps({'event': 'chunk', 'data': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'data': str(exc)})}\n\n"
            return

        yield f"data: {json.dumps({'event': 'done', 'data': ''})}\n\n"

    @staticmethod
    def _build_grounded_system_prompt() -> str:
        return (
            "You are DocSense, a precise and trustworthy AI document question-answering assistant.\n\n"
            "STRICT GROUNDING & SAFETY BOUNDARIES:\n"
            "1. You must answer the user's query STRICTLY based on the provided evidence chunks from the user's documents.\n"
            "2. If the retrieved evidence does NOT contain the information needed to answer the query (e.g. out-of-scope questions, generic programming tasks, unmentioned topics, or completely unrelated subjects), you MUST explicitly state that the provided documents do not contain information to answer this question. Do NOT hallucinate, guess, or use external ungrounded parametric knowledge to answer document questions.\n"
            "3. If the user asks a general conversational greeting (e.g. 'hi', 'hello', 'who are you'), respond politely and briefly remind them to ask questions about their uploaded documents.\n"
            "4. If the evidence only partially answers the query, answer the supported parts faithfully and explicitly state what aspects are not covered in the documents.\n\n"
            "FORMATTING & STYLE RULES:\n"
            "- Do NOT include raw chunk IDs, database IDs, or internal bracket tags like [1], 【1†L1-L2】, or (chunk_id=X) in your text — the citation system attaches sources separately.\n"
            "- Do NOT refer to 'chunk 1' or 'the retrieved chunks'. Refer to 'the document' or 'the provided material' if necessary.\n"
            "- Use clean markdown formatting: **bold** for emphasis, bullet lists for multiple points, headers (##) for sections, and tables where appropriate.\n"
            "- CRITICAL: Do NOT output raw HTML tags (such as <ul>, <li>, <p>, <table>, <br>, <span>). Always use clean standard Markdown for lists, tables, and typography.\n"
            "- When producing tables, always place each table row on its own new line with standard markdown syntax (| col1 | col2 |).\n"
            "- Be direct, concise, and professional."
        )

    # ------------------------------------------------------------------
    # Composed RAG pipeline helpers (non-streaming generation + revision)
    # ------------------------------------------------------------------

    def generate_answer(
        self,
        query: str,
        evidence: list[ChunkResult],
        temperature: float = 0.0,
    ) -> str:
        """Generate a grounded (non-streaming) answer from evidence.

        Uses the same grounding contract as :meth:`stream_answer`: the model
        is instructed to answer using only the provided evidence chunks.
        """
        system_prompt = self._build_grounded_system_prompt()
        evidence_summary = self._format_evidence(evidence)
        user_prompt = (
            f"User query: {query}\n\n"
            f"Evidence chunks:\n{evidence_summary}"
        )

        try:
            t0 = time.perf_counter()
            result = self.llm_service.complete(
                system_prompt,
                user_prompt,
                temperature=temperature,
            )
            logger.info("LLM generate_answer: %.3fs", time.perf_counter() - t0)
            return result
        except LLMError as exc:
            raise ServiceUnavailableError(
                f"Answer generation failed: {exc}"
            ) from exc

    def revise_answer(
        self,
        query: str,
        evidence: list[ChunkResult],
        answer: str,
        verification: VerificationResponse,
        temperature: float = 0.0,
    ) -> str:
        """Revise a non-grounded answer using verification feedback (Flow 4).

        The previous answer plus the verification issues are fed back to the
        LLM so every claim can be re-grounded in the evidence before a final
        verification pass.
        """
        evidence_summary = self._format_evidence(evidence)
        issue_lines = self._format_verification_issues(verification)
        user_prompt = (
            f"User query: {query}\n\n"
            f"Previous answer:\n{answer}\n\n"
            f"Verification feedback:\n{issue_lines}\n\n"
            f"Evidence chunks:\n{evidence_summary}"
        )

        try:
            t0 = time.perf_counter()
            result = self.llm_service.complete(
                REVISION_SYSTEM_PROMPT,
                user_prompt,
                temperature=temperature,
            )
            logger.info("LLM revise_answer: %.3fs", time.perf_counter() - t0)
            return result
        except LLMError as exc:
            raise ServiceUnavailableError(
                f"Answer revision failed: {exc}"
            ) from exc

    @staticmethod
    def _format_verification_issues(verification: VerificationResponse) -> str:
        lines = [
            f"supported={verification.supported}",
            f"citations_correct={verification.citations_correct}",
        ]
        if verification.explanation:
            lines.append(f"explanation={verification.explanation}")
        if verification.issues:
            lines.append("issues:")
            for issue in verification.issues:
                lines.append(
                    f"- {issue.citation_text} "
                    f"(claimed document={issue.claimed_document_id}, "
                    f"page={issue.claimed_page}): {issue.issue}"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # FR-023 — Web Search
    # ---------------------------------------------------------------------------

    def web_search(
        self,
        request: WebSearchRequest,
    ) -> WebSearchResponse:
        """Perform optional external web search."""
        provider = self._build_web_search_provider()
        results = provider.search(
            query=request.query,
            max_results=request.max_results,
        )

        return WebSearchResponse(
            query=request.query,
            results=results,
            provider="duckduckgo",
        )

    @staticmethod
    def _build_web_search_provider() -> WebSearchProvider:
        return WebSearchProvider()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_evidence(chunks: list[ChunkResult]) -> str:
        lines: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            meta_parts = [
                f"chunk_id={chunk.chunk_id}",
                f"document_id={chunk.document_id}",
                f"page={chunk.page_number}",
            ]
            if chunk.page_numbers:
                meta_parts.append(f"pages={chunk.page_numbers}")
            meta = ", ".join(meta_parts)
            lines.append(f"[{i}] ({meta}) {chunk.content}")
        return "\n".join(lines)
