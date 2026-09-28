from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.services.diagram_service import diagram_service
from app.diagram.registry import (
    get_all_diagram_types,
    get_all_diagram_kinds,
    get_all_output_formats,
    get_supported_kinds,
    resolve_diagram_type,
)

router = APIRouter(prefix="/diagram", tags=["Diagram"])


class GenerateRequest(BaseModel):
    diagram_type: str = Field(default="mermaid", description="Diagram engine type")
    diagram_kind: str = Field(default="flowchart", description="Type of diagram")
    source: str = Field(..., description="Diagram source code")
    output_format: str = Field(default="svg", description="Output format")
    max_attempts: Optional[int] = Field(default=None, description="Maximum retry attempts")


class GenerateResponse(BaseModel):
    success: bool
    diagram_id: str
    diagram_type: str
    diagram_kind: str
    source: str
    output_format: str
    content_base64: str = ""
    content_type: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: float = 0.0
    attempt: int = 1


class DiagramTypeInfo(BaseModel):
    type: str
    name: str
    supported_kinds: List[str]
    output_formats: List[str]


class DiagramTypesResponse(BaseModel):
    types: List[DiagramTypeInfo]
    default_type: str = "mermaid"


class DiagramKindsResponse(BaseModel):
    kinds: List[Dict[str, str]]
    default_kind: str = "flowchart"


class OutputFormatsResponse(BaseModel):
    formats: List[str]
    default_format: str = "svg"


class HealthResponse(BaseModel):
    healthy: bool
    kroki: Dict[str, Any]


@router.post("/generate", response_model=GenerateResponse)
async def generate_diagram(request: GenerateRequest):
    try:
        resolve_diagram_type(request.diagram_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await diagram_service.generate_with_retry(
        diagram_type=request.diagram_type,
        diagram_kind=request.diagram_kind,
        source=request.source,
        output_format=request.output_format,
        max_attempts=request.max_attempts,
    )

    return GenerateResponse(
        success=result.success,
        diagram_id=result.diagram_id,
        diagram_type=result.diagram_type.value,
        diagram_kind=result.diagram_kind.value,
        source=result.source,
        output_format=result.output_format.value,
        content_base64=result.content_base64,
        content_type=result.content_type,
        error_type=result.error_type,
        error_message=result.error_message,
        execution_time=result.execution_time,
        attempt=result.attempt,
    )


@router.get("/types", response_model=DiagramTypesResponse)
async def get_diagram_types():
    types_info = []
    for dt in get_all_diagram_types():
        kinds = get_supported_kinds(dt)
        types_info.append(DiagramTypeInfo(
            type=dt.value,
            name=dt.value.capitalize(),
            supported_kinds=[k.value for k in kinds],
            output_formats=[f.value for f in get_all_output_formats()],
        ))

    return DiagramTypesResponse(types=types_info)


@router.get("/kinds", response_model=DiagramKindsResponse)
async def get_diagram_kinds(diagram_type: str = "mermaid"):
    try:
        dt = resolve_diagram_type(diagram_type)
    except ValueError:
        dt = resolve_diagram_type("mermaid")

    kinds = get_supported_kinds(dt)
    return DiagramKindsResponse(
        kinds=[{"id": k.value, "name": k.value.capitalize()} for k in kinds],
    )


@router.get("/formats", response_model=OutputFormatsResponse)
async def get_output_formats():
    return OutputFormatsResponse(
        formats=[f.value for f in get_all_output_formats()],
    )


@router.get("/health", response_model=HealthResponse)
async def diagram_health():
    health = await diagram_service.health_check()
    return HealthResponse(healthy=health["healthy"], kroki=health["kroki"])