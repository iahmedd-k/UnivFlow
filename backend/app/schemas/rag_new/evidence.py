from pydantic import BaseModel, Field

from app.schemas.retrieval import ChunkResult


class EvidenceVerdict(BaseModel):
    """Result of an evidence sufficiency grading pass (FR-015).

    ``sufficient`` is the final decision externalized to downstream features
    (e.g. FR-020 abstention). The grading decision is deliberately kept
    separate from answer generation.
    """

    sufficient: bool
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Grading confidence / overall relevance score when available",
    )
    reason: str = Field(
        ...,
        description="Brief reason for the grading decision",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Important information absent from the evidence when insufficient",
    )


class RefinedQuery(BaseModel):
    """A corrective search query produced for a follow-up retrieval pass."""

    query: str = Field(..., min_length=1, description="Refined search query")
    rationale: str = Field(default="", description="Free-text rationale for the refinement")


class CorrectiveRetrievalResponse(BaseModel):
    """Result of a bounded corrective retrieval run (FR-016).

    ``sufficient=False`` with the attached ``verdict`` is the explicit
    insufficient-evidence signal that a downstream step (FR-020) can use to
    abstain. Chunk provenance (page numbers, document ids, metadata) is
    preserved on each item in ``evidence``.
    """

    original_query: str
    final_query: str
    sufficient: bool
    evidence: list[ChunkResult]
    verdict: EvidenceVerdict
    attempts_used: int
    max_attempts: int
    corrective_queries: list[str] = Field(default_factory=list)