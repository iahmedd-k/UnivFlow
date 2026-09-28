from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.services.diagram_service import diagram_service


class GenerateDiagramRequest(BaseModel):
    diagram_type: str = Field(default="mermaid", description="Diagram engine type (mermaid, plantuml, graphviz, etc.)")
    diagram_kind: str = Field(default="flowchart", description="Type of diagram (flowchart, sequence, class, er, state, gantt, etc.)")
    source: str = Field(..., description="Diagram source code (e.g., Mermaid syntax)")
    output_format: str = Field(default="svg", description="Output format (svg, png, pdf)")
    max_attempts: Optional[int] = Field(default=None, description="Maximum retry attempts")


class GenerateDiagramResponse(BaseModel):
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


async def generate_diagram(request: GenerateDiagramRequest) -> GenerateDiagramResponse:
    result = await diagram_service.generate_with_retry(
        diagram_type=request.diagram_type,
        diagram_kind=request.diagram_kind,
        source=request.source,
        output_format=request.output_format,
        max_attempts=request.max_attempts,
    )

    return GenerateDiagramResponse(
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


def get_generate_diagram_tool_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "generate_diagram",
            "description": "Generate a diagram using Mermaid (default) or other Kroki-supported diagram engines. Supports flowcharts, sequence diagrams, class diagrams, ER diagrams, state diagrams, Gantt charts, and more.",
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "description": "Diagram engine: mermaid (default), plantuml, graphviz, d2, erd, bpmn, excalidraw, vega, vega-lite, wavedrom",
                        "default": "mermaid",
                    },
                    "diagram_kind": {
                        "type": "string",
                        "description": "Type of diagram: flowchart (default), sequence, class, er, state, gantt, pie, gitgraph, journey, requirement, c4context, c4container, c4component, c4code, timeline, quadrant, mindmap, sankey, block, packet",
                        "default": "flowchart",
                    },
                    "source": {
                        "type": "string",
                        "description": "Diagram source code in the appropriate syntax (e.g., Mermaid syntax for mermaid diagrams)",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Output format: svg (default), png, pdf",
                        "default": "svg",
                    },
                    "max_attempts": {
                        "type": "integer",
                        "description": "Maximum retry attempts for rendering errors",
                        "default": 2,
                    },
                },
                "required": ["source"],
            },
        },
    }


async def handle_generate_diagram_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    request = GenerateDiagramRequest(**arguments)
    response = await generate_diagram(request)
    return response.model_dump()