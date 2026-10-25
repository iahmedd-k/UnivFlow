from typing import Self

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    """Input payload for a hybrid retrieval query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural language query to retrieve chunks for",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of top results to return",
    )


class ChunkResult(BaseModel):
    """Internal chunk result with full provenance — used by the pipeline."""

    chunk_id: int
    document_id: int
    content: str
    page_number: int
    page_numbers: list[int] = Field(default_factory=list)
    content_type: str
    metadata: dict = Field(default_factory=dict)
    score: float
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    """Internal search response — transformed into SearchApiResponse at the endpoint."""

    query: str
    results: list[ChunkResult]


# ---------------------------------------------------------------------------
# Frontend-facing response
# ---------------------------------------------------------------------------


class SearchResultItem(BaseModel):
    """A single search result trimmed for frontend display."""

    chunk_id: int = Field(..., description="Unique chunk identifier")
    document_id: int = Field(..., description="Source document id")
    page_number: int = Field(..., description="Page number in the source document")
    content: str = Field(..., description="Chunk text content")
    score: float = Field(..., description="Relevance score (higher = more relevant)")
    content_type: str = Field(default="text", description="Content type")


class SearchApiResponse(BaseModel):
    """Clean, frontend-friendly search response."""

    query: str = Field(..., description="The original search query")
    results: list[SearchResultItem] = Field(
        default_factory=list,
        description="Retrieved chunks ranked by relevance",
    )
    total_results: int = Field(..., description="Number of results returned")

    @classmethod
    def from_search_response(cls, search: SearchResponse) -> Self:
        """Transform an internal SearchResponse into a clean SearchApiResponse."""
        results = [
            SearchResultItem(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                page_number=r.page_number,
                content=r.content,
                score=r.rerank_score if r.rerank_score is not None else r.score,
                content_type=r.content_type,
            )
            for r in search.results
        ]
        return cls(
            query=search.query,
            results=results,
            total_results=len(results),
        )
