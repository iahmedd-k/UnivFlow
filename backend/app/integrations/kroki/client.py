import httpx
import logging
import base64
import zlib
from typing import Optional

from app.core.config import settings
from app.integrations.kroki.schemas import (
    KrokiRenderRequest,
    KrokiRenderResponse,
    KrokiHealthResponse,
)
from app.integrations.kroki.exceptions import (
    KrokiUnavailableError,
    DiagramRenderError,
    DiagramTimeoutError,
    DiagramSizeLimitError,
    KrokiAPIError,
)

logger = logging.getLogger(__name__)


class KrokiClient:
    def __init__(self):
        self.base_url = settings.kroki_base_url.rstrip("/")
        self.timeout = settings.kroki_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _encode_diagram_source(self, source: str) -> str:
        """Encode diagram source using Kroki's URL encoding (deflate + base64)."""
        compressed = zlib.compress(source.encode("utf-8"))
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
        return encoded

    async def health_check(self) -> KrokiHealthResponse:
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/")
            response.raise_for_status()
            return KrokiHealthResponse(status="healthy", version="unknown")
        except httpx.ConnectError as e:
            logger.error(f"Kroki connection failed: {e}")
            raise KrokiUnavailableError("Cannot connect to Kroki service")
        except httpx.TimeoutException as e:
            logger.error(f"Kroki health check timeout: {e}")
            raise KrokiUnavailableError("Kroki service timed out")
        except Exception as e:
            logger.error(f"Kroki health check error: {e}")
            raise KrokiUnavailableError(str(e))

    async def render_diagram(self, request: KrokiRenderRequest) -> KrokiRenderResponse:
        if len(request.diagram_source.encode("utf-8")) > settings.diagram_max_source_bytes:
            raise DiagramSizeLimitError(
                f"Diagram source exceeds maximum size of {settings.diagram_max_source_bytes} bytes"
            )

        client = await self._get_client()

        try:
            encoded_source = self._encode_diagram_source(request.diagram_source)
            url = f"{self.base_url}/{request.diagram_type}/{request.output_format}/{encoded_source}"

            response = await client.get(url)

            if response.status_code == 400:
                error_detail = response.text
                raise DiagramRenderError(
                    "Diagram rendering failed due to syntax error",
                    details=error_detail,
                )

            if response.status_code == 413:
                raise DiagramSizeLimitError("Diagram source too large for Kroki")

            if response.status_code == 408 or response.status_code == 504:
                raise DiagramTimeoutError()

            if response.status_code == 404:
                raise DiagramRenderError(
                    "Diagram type not found",
                    details=f"Type '{request.diagram_type}' may not be supported by this Kroki instance",
                )

            response.raise_for_status()

            return KrokiRenderResponse(
                success=True,
                content=response.content,
                content_type=response.headers.get("content-type", ""),
            )

        except httpx.TimeoutException:
            raise DiagramTimeoutError()
        except httpx.ConnectError as e:
            logger.error(f"Kroki connection error: {e}")
            raise KrokiUnavailableError("Cannot connect to Kroki service")
        except (
            DiagramRenderError,
            DiagramTimeoutError,
            DiagramSizeLimitError,
            KrokiUnavailableError,
        ):
            raise
        except Exception as e:
            logger.error(f"Kroki render error: {e}")
            raise KrokiAPIError(500, str(e))

    async def render_mermaid(
        self,
        source: str,
        output_format: str = "svg",
        kind: str = "flowchart",
    ) -> KrokiRenderResponse:
        request = KrokiRenderRequest(
            diagram_source=source,
            diagram_type="mermaid",
            output_format=output_format,
        )
        return await self.render_diagram(request)


kroki_client = KrokiClient()