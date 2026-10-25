from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceVerdict
from app.schemas.retrieval import ChunkResult


# ---------------------------------------------------------------------------
# FR-018 — Page/Source Citations
# ---------------------------------------------------------------------------


class CitationRequest(BaseModel):
    """Input payload for generating page/source citations."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The user query that the answer addresses",
    )
    answer: str = Field(
        ...,
        min_length=1,
        description="The grounded answer to generate citations for",
    )
    evidence: list[ChunkResult] = Field(
        ...,
        min_length=1,
        description="Evidence chunks used to generate the answer",
    )


class SourceCitation(BaseModel):
    """A single citation linking a span in the answer to a source."""

    text: str = Field(
        ...,
        description="The text span from the answer that is being cited",
    )
    document_id: int = Field(..., description="Source document id")
    page_number: int = Field(..., description="Page number in the source document")
    chunk_id: int | None = Field(
        default=None,
        description="Source chunk id when available",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Citation confidence score",
    )


class CitationResponse(BaseModel):
    """Generated citations for a grounded answer (FR-018)."""

    query: str
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FR-019 — Answer and Citation Verification
# ---------------------------------------------------------------------------


class VerificationRequest(BaseModel):
    """Input payload for verifying an answer against evidence."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The original user query",
    )
    answer: str = Field(
        ...,
        min_length=1,
        description="The generated answer to verify",
    )
    evidence: list[ChunkResult] = Field(
        ...,
        min_length=1,
        description="Evidence chunks the answer was grounded on",
    )


class CitationMismatch(BaseModel):
    """A specific citation that does not match the evidence."""

    citation_text: str = Field(..., description="The problematic citation text")
    claimed_document_id: int = Field(..., description="Document id claimed by the citation")
    claimed_page: int = Field(..., description="Page number claimed by the citation")
    issue: str = Field(
        ...,
        description="Description of the mismatch",
    )


class VerificationResponse(BaseModel):
    """Verification result for an answer and its citations (FR-019)."""

    supported: bool = Field(
        ...,
        description="Whether the answer is supported by the evidence",
    )
    citations_correct: bool = Field(
        ...,
        description="Whether all citations point to correct sources",
    )
    issues: list[CitationMismatch] = Field(
        default_factory=list,
        description="Specific citation mismatches when any",
    )
    explanation: str = Field(
        default="",
        description="Brief explanation of the verification outcome",
    )


# ---------------------------------------------------------------------------
# FR-020 — Explicit Abstention
# ---------------------------------------------------------------------------


class AbstentionRequest(BaseModel):
    """Input payload for deciding whether to abstain from answering."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The original user query",
    )
    evidence: list[ChunkResult] = Field(
        default_factory=list,
        description="Evidence chunks retrieved for the query",
    )
    verdict: EvidenceVerdict = Field(
        ...,
        description="Evidence sufficiency verdict from FR-015",
    )
    answer: str | None = Field(
        default=None,
        description="The generated answer (if any) before abstention check",
    )


class AbstentionResponse(BaseModel):
    """Abstention decision and message (FR-020)."""

    abstain: bool = Field(
        ...,
        description="Whether the system should abstain from providing an answer",
    )
    reason: str = Field(
        ...,
        description="Clear reason for the abstention decision",
    )
    suggestion: str = Field(
        default="",
        description="Optional suggestion for the user (e.g. rephrase the query)",
    )


# ---------------------------------------------------------------------------
# FR-021 — Streaming Chat Responses
# ---------------------------------------------------------------------------


class StreamChatRequest(BaseModel):
    """Input payload for streaming a grounded chat response."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The user query to generate a grounded response for",
    )
    evidence: list[ChunkResult] = Field(
        default_factory=list,
        description="Evidence chunks to ground the response on",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM sampling temperature",
    )


class StreamChunk(BaseModel):
    """A single chunk in a streaming response."""

    event: str = Field(
        default="chunk",
        description="Event type: chunk, done, or error",
    )
    data: str = Field(
        default="",
        description="Content of this streaming chunk",
    )


# ---------------------------------------------------------------------------
# FR-023 — Optional External Web Search
# ---------------------------------------------------------------------------


class WebSearchRequest(BaseModel):
    """Input payload for optional external web search."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The search query to look up externally",
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of results to return",
    )


class WebSearchResultItem(BaseModel):
    """A single external web search result."""

    title: str = Field(..., description="Result title")
    url: str = Field(..., description="Result URL")
    snippet: str = Field(default="", description="Result snippet or summary")
    rank: int = Field(..., description="Result rank (1-based)")


class WebSearchResponse(BaseModel):
    """External web search results (FR-023)."""

    query: str
    results: list[WebSearchResultItem] = Field(default_factory=list)
    provider: str = Field(
        default="duckduckgo",
        description="Search provider used",
    )
