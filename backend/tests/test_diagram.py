import pytest
from app.diagram import (
    resolve_diagram_type,
    resolve_diagram_kind,
    resolve_output_format,
    get_all_diagram_types,
    get_all_diagram_kinds,
    get_all_output_formats,
    get_supported_kinds,
    is_kind_supported_for_type,
    DiagramType,
    DiagramKind,
    OutputFormat,
)
from app.diagram.models import (
    DiagramRequest,
    DiagramResult,
    DiagramStatus,
    DiagramType as ModelDiagramType,
    DiagramKind as ModelDiagramKind,
    OutputFormat as ModelOutputFormat,
)


class TestDiagramTypeResolution:
    def test_mermaid(self):
        dt = resolve_diagram_type("mermaid")
        assert dt == DiagramType.MERMAID

    def test_plantuml(self):
        dt = resolve_diagram_type("plantuml")
        assert dt == DiagramType.PLANTUML

    def test_graphviz(self):
        dt = resolve_diagram_type("graphviz")
        assert dt == DiagramType.GRAPHVIZ

    def test_d2(self):
        dt = resolve_diagram_type("d2")
        assert dt == DiagramType.D2

    def test_erd(self):
        dt = resolve_diagram_type("erd")
        assert dt == DiagramType.ERD

    def test_bpmn(self):
        dt = resolve_diagram_type("bpmn")
        assert dt == DiagramType.BPMN

    def test_excalidraw(self):
        dt = resolve_diagram_type("excalidraw")
        assert dt == DiagramType.EXCALIDRAW

    def test_vega(self):
        dt = resolve_diagram_type("vega")
        assert dt == DiagramType.VEGA

    def test_vega_lite(self):
        dt = resolve_diagram_type("vega-lite")
        assert dt == DiagramType.VEGALITE

    def test_wavedrom(self):
        dt = resolve_diagram_type("wavedrom")
        assert dt == DiagramType.WAVEDROM

    def test_structurizr(self):
        dt = resolve_diagram_type("structurizr")
        assert dt == DiagramType.STRUCTURIZR

    def test_wireviz(self):
        dt = resolve_diagram_type("wireviz")
        assert dt == DiagramType.WIREVIZ

    def test_case_insensitive(self):
        dt = resolve_diagram_type("MERMAID")
        assert dt == DiagramType.MERMAID

        dt = resolve_diagram_type("PlantUML")
        assert dt == DiagramType.PLANTUML

    def test_unsupported_type(self):
        with pytest.raises(ValueError):
            resolve_diagram_type("unsupported")


class TestDiagramKindResolution:
    def test_flowchart(self):
        dk = resolve_diagram_kind("flowchart")
        assert dk == DiagramKind.FLOWCHART

    def test_sequence(self):
        dk = resolve_diagram_kind("sequence")
        assert dk == DiagramKind.SEQUENCE

    def test_class(self):
        dk = resolve_diagram_kind("class")
        assert dk == DiagramKind.CLASS

    def test_er(self):
        dk = resolve_diagram_kind("er")
        assert dk == DiagramKind.ER

    def test_state(self):
        dk = resolve_diagram_kind("state")
        assert dk == DiagramKind.STATE

    def test_gantt(self):
        dk = resolve_diagram_kind("gantt")
        assert dk == DiagramKind.GANTT

    def test_pie(self):
        dk = resolve_diagram_kind("pie")
        assert dk == DiagramKind.PIE

    def test_gitgraph(self):
        dk = resolve_diagram_kind("gitgraph")
        assert dk == DiagramKind.GITGRAPH

    def test_journey(self):
        dk = resolve_diagram_kind("journey")
        assert dk == DiagramKind.JOURNEY

    def test_requirement(self):
        dk = resolve_diagram_kind("requirement")
        assert dk == DiagramKind.REQUIREMENT

    def test_c4_context(self):
        dk = resolve_diagram_kind("c4context")
        assert dk == DiagramKind.C4_CONTEXT

    def test_c4_container(self):
        dk = resolve_diagram_kind("c4container")
        assert dk == DiagramKind.C4_CONTAINER

    def test_c4_component(self):
        dk = resolve_diagram_kind("c4component")
        assert dk == DiagramKind.C4_COMPONENT

    def test_c4_code(self):
        dk = resolve_diagram_kind("c4code")
        assert dk == DiagramKind.C4_CODE

    def test_timeline(self):
        dk = resolve_diagram_kind("timeline")
        assert dk == DiagramKind.TIMELINE

    def test_quadrant(self):
        dk = resolve_diagram_kind("quadrant")
        assert dk == DiagramKind.QUADRANT

    def test_mindmap(self):
        dk = resolve_diagram_kind("mindmap")
        assert dk == DiagramKind.MINDMAP

    def test_sankey(self):
        dk = resolve_diagram_kind("sankey")
        assert dk == DiagramKind.SANKEY

    def test_block(self):
        dk = resolve_diagram_kind("block")
        assert dk == DiagramKind.BLOCK

    def test_packet(self):
        dk = resolve_diagram_kind("packet")
        assert dk == DiagramKind.PACKET

    def test_kind_specific_to_type(self):
        dk = resolve_diagram_kind("flowchart", DiagramType.MERMAID)
        assert dk == DiagramKind.FLOWCHART

    def test_unsupported_kind(self):
        with pytest.raises(ValueError):
            resolve_diagram_kind("unsupported")


class TestOutputFormatResolution:
    def test_svg(self):
        of = resolve_output_format("svg")
        assert of == OutputFormat.SVG

    def test_png(self):
        of = resolve_output_format("png")
        assert of == OutputFormat.PNG

    def test_pdf(self):
        of = resolve_output_format("pdf")
        assert of == OutputFormat.PDF

    def test_unsupported_format(self):
        with pytest.raises(ValueError):
            resolve_output_format("jpg")


class TestDiagramRegistry:
    def test_all_types(self):
        types = get_all_diagram_types()
        assert len(types) >= 12

        type_values = {t.value for t in types}
        assert "mermaid" in type_values
        assert "plantuml" in type_values
        assert "graphviz" in type_values
        assert "d2" in type_values
        assert "erd" in type_values
        assert "bpmn" in type_values
        assert "excalidraw" in type_values
        assert "vega" in type_values
        assert "vega-lite" in type_values
        assert "wavedrom" in type_values
        assert "structurizr" in type_values
        assert "wireviz" in type_values

    def test_all_kinds(self):
        kinds = get_all_diagram_kinds()
        assert len(kinds) >= 19

        kind_values = {k.value for k in kinds}
        assert "flowchart" in kind_values
        assert "sequence" in kind_values
        assert "class" in kind_values
        assert "er" in kind_values
        assert "state" in kind_values
        assert "gantt" in kind_values

    def test_all_formats(self):
        formats = get_all_output_formats()
        assert len(formats) == 3

        format_values = {f.value for f in formats}
        assert format_values == {"svg", "png", "pdf"}

    def test_mermaid_kinds(self):
        kinds = get_supported_kinds(DiagramType.MERMAID)
        assert len(kinds) >= 19
        assert DiagramKind.FLOWCHART in kinds
        assert DiagramKind.SEQUENCE in kinds
        assert DiagramKind.CLASS in kinds
        assert DiagramKind.ER in kinds
        assert DiagramKind.STATE in kinds
        assert DiagramKind.GANTT in kinds

    def test_kind_support_check(self):
        assert is_kind_supported_for_type(DiagramKind.FLOWCHART, DiagramType.MERMAID)
        assert is_kind_supported_for_type(DiagramKind.SEQUENCE, DiagramType.MERMAID)
        assert is_kind_supported_for_type(DiagramKind.CLASS, DiagramType.MERMAID)
        assert is_kind_supported_for_type(DiagramKind.ER, DiagramType.MERMAID)

    def test_plantuml_kinds(self):
        kinds = get_supported_kinds(DiagramType.PLANTUML)
        assert DiagramKind.SEQUENCE in kinds
        assert DiagramKind.CLASS in kinds
        assert DiagramKind.STATE in kinds


class TestDiagramModels:
    def test_diagram_request_creation(self):
        request = DiagramRequest(
            diagram_type=ModelDiagramType.MERMAID,
            diagram_kind=ModelDiagramKind.FLOWCHART,
            source="flowchart TD\nA --> B",
            output_format=ModelOutputFormat.SVG,
            attempt=1,
        )

        assert request.diagram_type == ModelDiagramType.MERMAID
        assert request.diagram_kind == ModelDiagramKind.FLOWCHART
        assert request.source == "flowchart TD\nA --> B"

    def test_diagram_result_creation(self):
        result = DiagramResult(
            success=True,
            status=DiagramStatus.SUCCESS,
            diagram_type=ModelDiagramType.MERMAID,
            diagram_kind=ModelDiagramKind.FLOWCHART,
            source="flowchart TD\nA --> B",
            output_format=ModelOutputFormat.SVG,
            content=b"fake svg content",
            content_type="image/svg+xml",
            execution_time=0.5,
            attempt=1,
        )

        assert result.success is True
        assert result.status == DiagramStatus.SUCCESS
        assert result.content_base64 != ""

        d = result.to_dict()
        assert d["diagram_id"].startswith("diag_")
        assert d["success"] is True
        assert d["content_base64"] != ""

    def test_diagram_result_error(self):
        result = DiagramResult.error_result(
            diagram_type=ModelDiagramType.MERMAID,
            diagram_kind=ModelDiagramKind.FLOWCHART,
            error_type="RenderError",
            error_message="Syntax error in diagram",
            status=DiagramStatus.RENDER_ERROR,
            attempt=1,
        )

        assert result.success is False
        assert result.status == DiagramStatus.RENDER_ERROR
        assert result.error_type == "RenderError"
        assert result.error_message == "Syntax error in diagram"

    def test_diagram_status_enum(self):
        assert DiagramStatus.SUCCESS.value == "success"
        assert DiagramStatus.ERROR.value == "error"
        assert DiagramStatus.TIMEOUT.value == "timeout"
        assert DiagramStatus.SIZE_LIMIT.value == "size_limit"
        assert DiagramStatus.UNSUPPORTED_TYPE.value == "unsupported_type"
        assert DiagramStatus.RENDER_ERROR.value == "render_error"
        assert DiagramStatus.BACKEND_UNAVAILABLE.value == "backend_unavailable"

    def test_diagram_type_enum(self):
        assert ModelDiagramType.MERMAID.value == "mermaid"
        assert ModelDiagramType.PLANTUML.value == "plantuml"
        assert ModelDiagramType.GRAPHVIZ.value == "graphviz"

    def test_diagram_kind_enum(self):
        assert ModelDiagramKind.FLOWCHART.value == "flowchart"
        assert ModelDiagramKind.SEQUENCE.value == "sequence"
        assert ModelDiagramKind.CLASS.value == "class"
        assert ModelDiagramKind.ER.value == "er"
        assert ModelDiagramKind.STATE.value == "state"
        assert ModelDiagramKind.GANTT.value == "gantt"

    def test_output_format_enum(self):
        assert ModelOutputFormat.SVG.value == "svg"
        assert ModelOutputFormat.PNG.value == "png"
        assert ModelOutputFormat.PDF.value == "pdf"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])