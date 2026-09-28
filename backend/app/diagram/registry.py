from typing import Dict, List, Optional, Set
from app.diagram.models import (
    DiagramType,
    DiagramKind,
    OutputFormat,
    DIAGRAM_TYPE_KINDS,
    MERMAID_KINDS,
)

DIAGRAM_TYPE_REGISTRY: Dict[str, DiagramType] = {
    "mermaid": DiagramType.MERMAID,
    "plantuml": DiagramType.PLANTUML,
    "graphviz": DiagramType.GRAPHVIZ,
    "d2": DiagramType.D2,
    "erd": DiagramType.ERD,
    "bpmn": DiagramType.BPMN,
    "excalidraw": DiagramType.EXCALIDRAW,
    "vega": DiagramType.VEGA,
    "vega-lite": DiagramType.VEGALITE,
    "wavedrom": DiagramType.WAVEDROM,
    "structurizr": DiagramType.STRUCTURIZR,
    "wireviz": DiagramType.WIREVIZ,
}

DIAGRAM_KIND_REGISTRY: Dict[str, DiagramKind] = {
    "flowchart": DiagramKind.FLOWCHART,
    "sequence": DiagramKind.SEQUENCE,
    "class": DiagramKind.CLASS,
    "er": DiagramKind.ER,
    "state": DiagramKind.STATE,
    "gantt": DiagramKind.GANTT,
    "pie": DiagramKind.PIE,
    "gitgraph": DiagramKind.GITGRAPH,
    "journey": DiagramKind.JOURNEY,
    "requirement": DiagramKind.REQUIREMENT,
    "c4context": DiagramKind.C4_CONTEXT,
    "c4container": DiagramKind.C4_CONTAINER,
    "c4component": DiagramKind.C4_COMPONENT,
    "c4code": DiagramKind.C4_CODE,
    "timeline": DiagramKind.TIMELINE,
    "quadrant": DiagramKind.QUADRANT,
    "mindmap": DiagramKind.MINDMAP,
    "sankey": DiagramKind.SANKEY,
    "block": DiagramKind.BLOCK,
    "packet": DiagramKind.PACKET,
}

OUTPUT_FORMAT_REGISTRY: Dict[str, OutputFormat] = {
    "svg": OutputFormat.SVG,
    "png": OutputFormat.PNG,
    "pdf": OutputFormat.PDF,
}


def resolve_diagram_type(type_str: str) -> DiagramType:
    normalized = type_str.strip().lower()
    if normalized in DIAGRAM_TYPE_REGISTRY:
        return DIAGRAM_TYPE_REGISTRY[normalized]
    raise ValueError(f"Unsupported diagram type: {type_str}. Supported: {list(DIAGRAM_TYPE_REGISTRY.keys())}")


def resolve_diagram_kind(kind_str: str, diagram_type: DiagramType = DiagramType.MERMAID) -> DiagramKind:
    normalized = kind_str.strip().lower()
    if normalized in DIAGRAM_KIND_REGISTRY:
        kind = DIAGRAM_KIND_REGISTRY[normalized]
        if kind in DIAGRAM_TYPE_KINDS.get(diagram_type, set()):
            return kind
        raise ValueError(f"Diagram kind '{kind_str}' not supported for type '{diagram_type.value}'")
    raise ValueError(f"Unsupported diagram kind: {kind_str}. Supported: {list(DIAGRAM_KIND_REGISTRY.keys())}")


def resolve_output_format(format_str: str) -> OutputFormat:
    normalized = format_str.strip().lower()
    if normalized in OUTPUT_FORMAT_REGISTRY:
        return OUTPUT_FORMAT_REGISTRY[normalized]
    raise ValueError(f"Unsupported output format: {format_str}. Supported: {list(OUTPUT_FORMAT_REGISTRY.keys())}")


def get_supported_kinds(diagram_type: DiagramType) -> List[DiagramKind]:
    return list(DIAGRAM_TYPE_KINDS.get(diagram_type, MERMAID_KINDS))


def get_all_diagram_types() -> List[DiagramType]:
    return list(DIAGRAM_TYPE_REGISTRY.values())


def get_all_diagram_kinds() -> List[DiagramKind]:
    return list(DIAGRAM_KIND_REGISTRY.values())


def get_all_output_formats() -> List[OutputFormat]:
    return list(OUTPUT_FORMAT_REGISTRY.values())


def is_kind_supported_for_type(kind: DiagramKind, diagram_type: DiagramType) -> bool:
    return kind in DIAGRAM_TYPE_KINDS.get(diagram_type, set())