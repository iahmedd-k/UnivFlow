import time
import logging
from typing import Optional, Dict, Any

from app.diagram.models import (
    DiagramRequest,
    DiagramResult,
    DiagramType,
    DiagramKind,
    OutputFormat,
    DiagramStatus,
)
from app.diagram.registry import (
    resolve_diagram_type,
    resolve_diagram_kind,
    resolve_output_format,
    is_kind_supported_for_type,
)
from app.integrations.kroki import kroki_client, DiagramRenderError, KrokiUnavailableError, DiagramTimeoutError, DiagramSizeLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)


class DiagramService:
    def __init__(self):
        self._client = kroki_client

    async def generate(
        self,
        diagram_type: str = "mermaid",
        diagram_kind: str = "flowchart",
        source: str = "",
        output_format: str = "svg",
        attempt: int = 1,
        validate_only: bool = False,
    ) -> DiagramResult:
        start_time = time.perf_counter()

        try:
            dt = resolve_diagram_type(diagram_type)
        except ValueError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Invalid diagram type: {e}")
            return DiagramResult.error_result(
                diagram_type=DiagramType.MERMAID,
                diagram_kind=DiagramKind.FLOWCHART,
                error_type="UnsupportedDiagramTypeError",
                error_message=str(e),
                status=DiagramStatus.UNSUPPORTED_TYPE,
                attempt=attempt,
                execution_time=execution_time,
            )

        try:
            dk = resolve_diagram_kind(diagram_kind, dt)
        except ValueError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Invalid diagram kind: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=DiagramKind.FLOWCHART,
                error_type="UnsupportedDiagramKindError",
                error_message=str(e),
                status=DiagramStatus.UNSUPPORTED_TYPE,
                attempt=attempt,
                execution_time=execution_time,
            )

        try:
            of = resolve_output_format(output_format)
        except ValueError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Invalid output format: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="UnsupportedOutputFormatError",
                error_message=str(e),
                status=DiagramStatus.UNSUPPORTED_TYPE,
                attempt=attempt,
                execution_time=execution_time,
            )

        if not source or not source.strip():
            execution_time = time.perf_counter() - start_time
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="ValidationError",
                error_message="Diagram source cannot be empty",
                status=DiagramStatus.ERROR,
                attempt=attempt,
                execution_time=execution_time,
            )

        if len(source.encode("utf-8")) > settings.diagram_max_source_bytes:
            execution_time = time.perf_counter() - start_time
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="DiagramSizeLimitError",
                error_message=f"Diagram source exceeds maximum size of {settings.diagram_max_source_bytes} bytes",
                status=DiagramStatus.SIZE_LIMIT,
                attempt=attempt,
                execution_time=execution_time,
            )

        # Validate syntax before rendering
        validation = await self._client.validate_diagram_source(dt.value, source)
        if not validation.get("valid", False):
            execution_time = time.perf_counter() - start_time
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="ValidationError",
                error_message=f"Syntax validation failed: {validation.get('error', 'Unknown error')}",
                status=DiagramStatus.RENDER_ERROR,
                attempt=attempt,
                execution_time=execution_time,
            )

        if validate_only:
            execution_time = time.perf_counter() - start_time
            return DiagramResult(
                success=True,
                diagram_id=f"val-{int(time.time())}",
                diagram_type=dt,
                diagram_kind=dk,
                source=source,
                output_format=of,
                content_base64="",
                content_type=validation.get("content_type", ""),
                status=DiagramStatus.SUCCESS,
                execution_time=execution_time,
                attempt=attempt,
            )

        request = DiagramRequest(
            diagram_type=dt,
            diagram_kind=dk,
            source=source.strip(),
            output_format=of,
            attempt=attempt,
        )

        try:
            kroki_response = await self._client.render_diagram(
                diagram_source=request.source,
                diagram_type=request.diagram_type.value,
                output_format=request.output_format.value,
            )

            execution_time = time.perf_counter() - start_time
            result = DiagramResult.from_kroki_response(kroki_response, request, execution_time)
            result.version = getattr(kroki_response, 'version', 1)
            result.endpoint = getattr(kroki_response, 'endpoint', 'unknown')
            return result

        except DiagramRenderError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Diagram render error: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="DiagramRenderError",
                error_message=f"Rendering failed: {e.message}. Details: {e.details}",
                status=DiagramStatus.RENDER_ERROR,
                attempt=attempt,
                execution_time=execution_time,
            )

        except DiagramTimeoutError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Diagram timeout: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="DiagramTimeoutError",
                error_message="Diagram rendering timed out",
                status=DiagramStatus.TIMEOUT,
                attempt=attempt,
                execution_time=execution_time,
            )

        except DiagramSizeLimitError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Diagram size limit: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="DiagramSizeLimitError",
                error_message=str(e),
                status=DiagramStatus.SIZE_LIMIT,
                attempt=attempt,
                execution_time=execution_time,
            )

        except KrokiUnavailableError as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"Kroki unavailable: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="KrokiUnavailableError",
                error_message=str(e),
                status=DiagramStatus.BACKEND_UNAVAILABLE,
                attempt=attempt,
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"Diagram generation error: {e}")
            return DiagramResult.error_result(
                diagram_type=dt,
                diagram_kind=dk,
                error_type="GenerationError",
                error_message=str(e),
                status=DiagramStatus.ERROR,
                attempt=attempt,
                execution_time=execution_time,
            )

    async def generate_with_retry(
        self,
        diagram_type: str = "mermaid",
        diagram_kind: str = "flowchart",
        source: str = "",
        output_format: str = "svg",
        max_attempts: int = None,
    ) -> DiagramResult:
        max_attempts = max_attempts or settings.diagram_max_attempts

        last_result = None
        for attempt in range(1, max_attempts + 1):
            result = await self.generate(
                diagram_type=diagram_type,
                diagram_kind=diagram_kind,
                source=source,
                output_format=output_format,
                attempt=attempt,
            )
            last_result = result

            if result.success:
                break

            if attempt < max_attempts and result.status == DiagramStatus.RENDER_ERROR:
                logger.info(f"Diagram attempt {attempt} failed, retrying...")
                continue

            if attempt < max_attempts:
                break

        return last_result

    async def validate_diagram(self, diagram_type: str, source: str) -> Dict[str, Any]:
        """Validate diagram source syntax without rendering."""
        try:
            dt = resolve_diagram_type(diagram_type)
            validation = await self._client.validate_diagram_source(dt.value, source)
            return validation
        except Exception as e:
            return {"valid": False, "error": str(e)}

    async def get_diagram_version(self, source: str) -> int:
        """Get version number for diagram source."""
        return self._client.get_diagram_version(source)

    async def health_check(self) -> dict:
        try:
            health = await self._client.health_check()
            return {
                "healthy": health.status == "healthy",
                "kroki": health.model_dump(),
            }
        except Exception as e:
            logger.error(f"Diagram service health check failed: {e}")
            return {
                "healthy": False,
                "kroki": {"status": "unhealthy", "error": str(e)},
            }


diagram_service = DiagramService()