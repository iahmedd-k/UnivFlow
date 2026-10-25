from pydantic import BaseModel, Field


class UsageResponse(BaseModel):
    """Authenticated user's current usage and quota information (FR-022)."""

    user_id: int = Field(..., description="Authenticated user id")
    documents_uploaded: int = Field(
        default=0,
        ge=0,
        description="Total documents uploaded by the user",
    )
    document_quota: int = Field(
        default=-1,
        description="Maximum documents allowed (-1 = unlimited)",
    )
    chunks_stored: int = Field(
        default=0,
        ge=0,
        description="Total chunks stored across all documents",
    )
    chunk_quota: int = Field(
        default=-1,
        description="Maximum chunks allowed (-1 = unlimited)",
    )
    queries_this_month: int = Field(
        default=0,
        ge=0,
        description="Queries executed in the current billing period",
    )
    query_quota: int = Field(
        default=-1,
        description="Maximum queries per month (-1 = unlimited)",
    )
