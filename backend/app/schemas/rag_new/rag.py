from typing import Self

from pydantic import BaseModel, Field

from app.schemas.chat import SourceCitation, VerificationResponse
from app.schemas.evidence import EvidenceVerdict
from app.schemas.query_analysis import QueryAnalysis
from app.schemas.retrieval import ChunkResult


class RagRequest(BaseModel):
    """Input payload for the composed end-to-end RAG pipeline (Flow 2 - Flow 5)."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The user question to answer",
    )
    conversation_id: int | None = Field(
        default=None,
        description="Optional conversation ID to continue a conversation",
    )
    document_ids: list[int] | None = Field(
        default=None,
        description="Optional list of document IDs to scope retrieval to",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Evidence results to retrieve per query (defaults to server config)",
    )
    max_revision_attempts: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Answer revision budget after a failed verification (defaults to server config)",
    )


class RagResponse(BaseModel):
    """Internal pipeline output — used between RAGService and the endpoint.

    Contains full pipeline details for logging/debugging. The endpoint
    transforms this into a clean ``ChatResponse`` for the frontend.
    """

    query: str
    query_analysis: QueryAnalysis
    evidence: list[ChunkResult]
    verdict: EvidenceVerdict
    answer: str | None = None
    citations: list[SourceCitation] = Field(default_factory=list)
    verification: VerificationResponse | None = None
    abstained: bool
    abstention_reason: str | None = None
    abstention_suggestion: str | None = None
    corrective_queries: list[str] = Field(default_factory=list)
    corrective_attempts: int = 0
    revision_attempts: int = 0


# ---------------------------------------------------------------------------
# Frontend-facing response schemas
# ---------------------------------------------------------------------------


class SourceChunk(BaseModel):
    """A trimmed evidence chunk for frontend display."""

    document_id: int = Field(..., description="Source document id")
    page_number: int = Field(..., description="Page number in the source document")
    content: str = Field(..., description="Chunk text content")
    score: float = Field(..., description="Relevance score")


class ChatResponse(BaseModel):
    """Clean, frontend-friendly response from the chat/RAG endpoint.

    Exposes only what the UI needs: the answer, citations, source evidence,
    and a clear abstention signal with user-facing messaging.
    """

    query: str = Field(..., description="The original user question")
    answer: str | None = Field(
        default=None,
        description="The grounded answer (null when abstained)",
    )
    citations: list[SourceCitation] = Field(
        default_factory=list,
        description="Citations linking answer spans to source documents",
    )
    sources: list[SourceChunk] = Field(
        default_factory=list,
        description="Evidence chunks used to ground the answer",
    )
    abstained: bool = Field(
        ...,
        description="Whether the system abstained from answering",
    )
    abstention_reason: str | None = Field(
        default=None,
        description="User-facing reason when abstained",
    )
    abstention_suggestion: str | None = Field(
        default=None,
        description="Suggestion for the user when abstained (e.g. rephrase)",
    )
    confidence: float | None = Field(
        default=None,
        description="Overall confidence score from evidence grading",
    )

    @classmethod
    def from_rag_response(cls, rag: RagResponse) -> Self:
        """Transform an internal RagResponse into a clean ChatResponse."""
        sources = [
            SourceChunk(
                document_id=c.document_id,
                page_number=c.page_number,
                content=c.content,
                score=c.rerank_score if c.rerank_score is not None else c.score,
            )
            for c in rag.evidence
        ]

        return cls(
            query=rag.query,
            answer=rag.answer,
            citations=rag.citations,
            sources=sources,
            abstained=rag.abstained,
            abstention_reason=rag.abstention_reason,
            abstention_suggestion=rag.abstention_suggestion,
            confidence=rag.verdict.confidence_score,
        )