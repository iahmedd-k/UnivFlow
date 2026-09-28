from typing import Optional, Literal
from pydantic import BaseModel, Field


class KrokiRenderRequest(BaseModel):
    diagram_source: str = Field(..., min_length=1)
    diagram_type: str = Field(default="mermaid")
    output_format: Literal["svg", "png", "pdf"] = Field(default="svg")


class KrokiRenderResponse(BaseModel):
    success: bool
    content: Optional[bytes] = None
    content_type: str = ""
    error: Optional[str] = None
    error_type: Optional[str] = None


class KrokiHealthResponse(BaseModel):
    status: str
    version: Optional[str] = None


class DiagramTypeInfo(BaseModel):
    type: str
    name: str
    supported_kinds: list[str]
    output_formats: list[str]