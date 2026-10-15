import httpx
import logging
import base64
import zlib
from typing import Optional, Dict, Any, List

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

# Local diagram renderers as fallback when Kroki is unavailable
LOCAL_RENDERERS = {
    "mermaid": "mermaid-cli",
    "plantuml": "plantuml",
    "graphviz": "dot",
    "d2": "d2",
    "nomnoml": "nomnoml",
}

DEFAULT_KROKI_URLS = [
    "https://kroki.io",
    "https://kroki.uniflow.dev",
    "https://kroki.vercel.app",
]


class KrokiClient:
    def __init__(self):
        self.base_url = settings.kroki_base_url.rstrip("/")
        self.fallback_urls = getattr(settings, 'kroki_fallback_urls', DEFAULT_KROKI_URLS)
        self.timeout = settings.kroki_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
        self._current_url_index = 0
        
        # Diagram version tracking
        self._diagram_versions: Dict[str, int] = {}

    def _get_current_base_url(self) -> str:
        if self._current_url_index == 0:
            return self.base_url
        elif self._current_url_index <= len(self.fallback_urls):
            return self.fallback_urls[self._current_url_index - 1]
        return self.base_url

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

    def _get_next_base_url(self) -> str:
        """Rotate to next available Kroki instance."""
        urls = [self.base_url] + self.fallback_urls
        self._current_url_index = (self._current_url_index + 1) % len(urls)
        return urls[self._current_url_index]

    async def health_check(self) -> KrokiHealthResponse:
        """Check health of current and fallback Kroki instances."""
        urls = [self.base_url] + self.fallback_urls
        for i, url in enumerate(urls):
            client = await self._get_client()
            try:
                response = await client.get(f"{url}/", timeout=5.0)
                response.raise_for_status()
                self._current_url_index = i
                return KrokiHealthResponse(status="healthy", version="unknown", endpoint=url)
            except Exception:
                continue
        
        # All endpoints failed
        return KrokiHealthResponse(status="unhealthy", version="unknown", endpoint="none")

    async def render_diagram(self, request: KrokiRenderRequest) -> KrokiRenderResponse:
        if len(request.diagram_source.encode("utf-8")) > settings.diagram_max_source_bytes:
            raise DiagramSizeLimitError(
                f"Diagram source exceeds maximum size of {settings.diagram_max_source_bytes} bytes"
            )

        # Track diagram version
        source_hash = hashlib.sha256(request.diagram_source.encode()).hexdigest()[:16]
        version = self._diagram_versions.get(source_hash, 0) + 1
        self._diagram_versions[source_hash] = version

        # Try primary and fallback Kroki instances
        urls = [self.base_url] + self.fallback_urls
        last_error = None
        
        for base_url in urls:
            client = await self._get_client()
            try:
                encoded_source = self._encode_diagram_source(request.diagram_source)
                url = f"{base_url}/{request.diagram_type}/{request.output_format}/{encoded_source}"

                response = await client.get(url, timeout=self.timeout)

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
                    version=version,
                    endpoint=base_url,
                )

            except httpx.TimeoutException:
                last_error = DiagramTimeoutError()
                logger.warning(f"Kroki timeout at {base_url}, trying fallback...")
                continue
            except httpx.ConnectError as e:
                last_error = KrokiUnavailableError(f"Cannot connect to Kroki at {base_url}")
                logger.warning(f"Kroki connection failed at {base_url}, trying fallback...")
                continue
            except (
                DiagramRenderError,
                DiagramTimeoutError,
                DiagramSizeLimitError,
                KrokiUnavailableError,
            ):
                raise
            except Exception as e:
                last_error = KrokiAPIError(500, str(e))
                logger.error(f"Kroki render error at {base_url}: {e}")
                continue
        
        # All endpoints failed, try local rendering as last resort
        try:
            local_result = await self._render_locally(request)
            if local_result:
                local_result.endpoint = "local"
                local_result.version = version
                return local_result
        except Exception as e:
            logger.error(f"Local rendering also failed: {e}")

        # Everything failed
        if last_error:
            raise last_error
        raise KrokiUnavailableError("All Kroki endpoints and local rendering failed")

    async def _render_locally(self, request: KrokiRenderRequest) -> Optional[KrokiRenderResponse]:
        """Attempt local rendering using CLI tools."""
        renderer = LOCAL_RENDERERS.get(request.diagram_type)
        if not renderer:
            return None
        
        import subprocess
        import tempfile
        import os
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{request.diagram_type}', delete=False) as f:
                f.write(request.diagram_source)
                temp_input = f.name
            
            temp_output = f"{temp_input}.{request.output_format}"
            
            # Map diagram types to CLI commands
            cmd_map = {
                "mermaid": ["mmdc", "-i", temp_input, "-o", temp_output],
                "plantuml": ["plantuml", "-t" + request.output_format, temp_input],
                "graphviz": ["dot", f"-T{request.output_format}", temp_input, "-o", temp_output],
                "d2": ["d2", temp_input, temp_output],
                "nomnoml": ["nomnoml", temp_input, temp_output],
            }
            
            cmd = cmd_map.get(request.diagram_type)
            if not cmd:
                return None
            
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(temp_output):
                with open(temp_output, 'rb') as f:
                    content = f.read()
                
                content_type = {
                    "svg": "image/svg+xml",
                    "png": "image/png",
                    "pdf": "application/pdf",
                }.get(request.output_format, "application/octet-stream")
                
                # Cleanup
                try:
                    os.unlink(temp_input)
                    os.unlink(temp_output)
                except:
                    pass
                
                return KrokiRenderResponse(
                    success=True,
                    content=content,
                    content_type=content_type,
                    version=1,
                    endpoint="local",
                )
        except Exception as e:
            logger.error(f"Local rendering failed: {e}")
        
        return None

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

    async def validate_diagram_source(self, diagram_type: str, source: str) -> Dict[str, Any]:
        """Validate diagram source syntax without rendering."""
        try:
            # Quick syntax check by attempting to render
            request = KrokiRenderRequest(
                diagram_source=source,
                diagram_type=diagram_type,
                output_format="svg",
            )
            result = await self.render_diagram(request)
            return {
                "valid": result.success,
                "content_type": result.content_type,
                "size_bytes": len(result.content) if result.content else 0,
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
            }

    def get_diagram_version(self, source: str) -> int:
        """Get the version number for a diagram source."""
        source_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
        return self._diagram_versions.get(source_hash, 0)


import hashlib

kroki_client = KrokiClient()