from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response envelope.

    Every successful endpoint wraps its payload in this structure so the
    frontend always receives a predictable shape:

    {
        "success": true,
        "data": { ... },
        "message": "..."
    }

    Errors already follow a similar shape from the exception handlers:
    {
        "success": false,
        "status_code": 4xx/5xx,
        "message": "...",
        "errors": [...]
    }
    """

    success: bool = Field(default=True, description="Whether the request succeeded")
    data: T | None = Field(default=None, description="Response payload")
    message: str = Field(default="", description="Human-readable status message")
    meta: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata (pagination, timing, etc.)",
    )
