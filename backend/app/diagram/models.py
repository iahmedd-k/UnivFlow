import uuid
import base64
from enum import Enum
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime


class DiagramStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    SIZE_LIMIT = "size_limit"
    UNSUPPORTED_TYPE = "unsupported_type"
    RENDER_ERROR = "render_error"
    BACKEND_UNAVAILABLE = "backend_unavailable"


class DiagramType(str, Enum):
    MERMAID = "mermaid"
    PLANTUML = "plantuml"
    GRAPHVIZ = "graphviz"
    D2 = "d2"
    ERD = "erd"
    BPMN = "bpmn"
    EXCALIDRAW = "excalidraw"
    VEGA = "vega"
    VEGALITE = "vega-lite"
    WAVEDROM = "wavedrom"
    STRUCTURIZR = "structurizr"
    WIREVIZ = "wireviz"


class DiagramKind(str, Enum):
    FLOWCHART = "flowchart"
    SEQUENCE = "sequence"
    CLASS = "class"
    ER = "er"
    STATE = "state"
    GANTT = "gantt"
    PIE = "pie"
    GITGRAPH = "gitgraph"
    JOURNEY = "journey"
    REQUIREMENT = "requirement"
    C4_CONTEXT = "c4context"
    C4_CONTAINER = "c4container"
    C4_COMPONENT = "c4component"
    C4_CODE = "c4code"
    TIMELINE = "timeline"
    QUADRANT = "quadrant"
    MINDMAP = "mindmap"
    SANKEY = "sankey"
    BLOCK = "block"
    PACKET = "packet"


class OutputFormat(str, Enum):
    SVG = "svg"
    PNG = "png"
    PDF = "pdf"


MERMAID_KINDS = {
    DiagramKind.FLOWCHART,
    DiagramKind.SEQUENCE,
    DiagramKind.CLASS,
    DiagramKind.ER,
    DiagramKind.STATE,
    DiagramKind.GANTT,
    DiagramKind.PIE,
    DiagramKind.GITGRAPH,
    DiagramKind.JOURNEY,
    DiagramKind.REQUIREMENT,
    DiagramKind.C4_CONTEXT,
    DiagramKind.C4_CONTAINER,
    DiagramKind.C4_COMPONENT,
    DiagramKind.C4_CODE,
    DiagramKind.TIMELINE,
    DiagramKind.QUADRANT,
    DiagramKind.MINDMAP,
    DiagramKind.SANKEY,
    DiagramKind.BLOCK,
    DiagramKind.PACKET,
}

DIAGRAM_TYPE_KINDS = {
    DiagramType.MERMAID: MERMAID_KINDS,
    DiagramType.PLANTUML: {
        DiagramKind.SEQUENCE,
        DiagramKind.CLASS,
        DiagramKind.STATE,
    },
    DiagramType.GRAPHVIZ: {DiagramKind.FLOWCHART},
    DiagramType.D2: {DiagramKind.FLOWCHART},
    DiagramType.ERD: {DiagramKind.ER},
}


@dataclass
class DiagramRequest:
    diagram_type: DiagramType = DiagramType.MERMAID
    diagram_kind: DiagramKind = DiagramKind.FLOWCHART
    source: str = ""
    output_format: OutputFormat = OutputFormat.SVG
    attempt: int = 1


@dataclass
class DiagramResult:
    diagram_id: str = field(default_factory=lambda: f"diag_{uuid.uuid4().hex[:8]}")
    success: bool = False
    status: DiagramStatus = DiagramStatus.ERROR

    diagram_type: DiagramType = DiagramType.MERMAID
    diagram_kind: DiagramKind = DiagramKind.FLOWCHART
    source: str = ""
    output_format: OutputFormat = OutputFormat.SVG

    content: Optional[bytes] = None
    content_type: str = ""
    content_base64: str = ""

    error_type: Optional[str] = None
    error_message: Optional[str] = None

    execution_time: float = 0.0
    attempt: int = 1

    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.content and not self.content_base64:
            self.content_base64 = base64.b64encode(self.content).decode("ascii")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagram_id": self.diagram_id,
            "success": self.success,
            "status": self.status.value,
            "diagram_type": self.diagram_type.value,
            "diagram_kind": self.diagram_kind.value,
            "source": self.source,
            "output_format": self.output_format.value,
            "content_base64": self.content_base64,
            "content_type": self.content_type,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "execution_time": self.execution_time,
            "attempt": self.attempt,
            "metadata": self.metadata,
        }

    @classmethod
    def from_kroki_response(
        cls,
        kroki_response,
        request: "DiagramRequest",
        execution_time: float,
    ) -> "DiagramResult":
        if kroki_response.success:
            content_base64 = ""
            if kroki_response.content:
                content_base64 = base64.b64encode(kroki_response.content).decode("ascii")

            return cls(
                success=True,
                status=DiagramStatus.SUCCESS,
                diagram_type=request.diagram_type,
                diagram_kind=request.diagram_kind,
                source=request.source,
                output_format=request.output_format,
                content=kroki_response.content,
                content_type=kroki_response.content_type,
                content_base64=content_base64,
                execution_time=execution_time,
                attempt=request.attempt,
            )
        else:
            return cls.error_result(
                diagram_type=request.diagram_type,
                diagram_kind=request.diagram_kind,
                error_type=kroki_response.error_type or "RenderError",
                error_message=kroki_response.error or "Unknown rendering error",
                status=DiagramStatus.RENDER_ERROR,
                attempt=request.attempt,
                execution_time=execution_time,
            )

    @classmethod
    def error_result(
        cls,
        diagram_type: DiagramType,
        diagram_kind: DiagramKind,
        error_type: str,
        error_message: str,
        status: DiagramStatus = DiagramStatus.ERROR,
        attempt: int = 1,
        execution_time: float = 0.0,
    ) -> "DiagramResult":
        return cls(
            success=False,
            status=status,
            diagram_type=diagram_type,
            diagram_kind=diagram_kind,
            error_type=error_type,
            error_message=error_message,
            attempt=attempt,
            execution_time=execution_time,
        )