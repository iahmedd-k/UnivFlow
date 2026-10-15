import httpx
import logging
from typing import List, Optional, Dict, Any

from app.core.config import settings
from app.integrations.piston.schemas import (
    PistonExecuteResponse,
    PistonRunRequest,
    PistonRuntime,
    PistonRuntimesResponse,
    PistonHealthResponse,
)
from app.integrations.piston.exceptions import (
    PistonUnavailableError,
    RuntimeUnavailableError,
    ExecutionTimeoutError,
    ExecutionLimitError,
    PistonAPIError,
)

logger = logging.getLogger(__name__)


class PistonClient:
    def __init__(self):
        self.base_url = settings.piston_base_url.rstrip("/")
        self.timeout = settings.piston_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
        self._runtimes_cache: Optional[List[PistonRuntime]] = None
        
        # Resource limits (can be overridden per-request)
        self.default_memory_limit = getattr(settings, 'piston_memory_limit_mb', 256)  # MB
        self.default_cpu_limit = getattr(settings, 'piston_cpu_limit', 1.0)  # CPU cores
        self.default_packages = getattr(settings, 'piston_default_packages', {})  # language -> list of packages

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> PistonHealthResponse:
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/api/v2/health")
            response.raise_for_status()
            data = response.json()
            runtimes = await self.get_runtimes()
            return PistonHealthResponse(
                status=data.get("status", "unknown"),
                version=data.get("version", "unknown"),
                runtimes_count=len(runtimes),
            )
        except httpx.ConnectError as e:
            logger.error(f"Piston connection failed: {e}")
            raise PistonUnavailableError("Cannot connect to Piston service")
        except httpx.TimeoutException as e:
            logger.error(f"Piston health check timeout: {e}")
            raise PistonUnavailableError("Piston service timed out")
        except Exception as e:
            logger.error(f"Piston health check error: {e}")
            raise PistonUnavailableError(str(e))

    async def get_runtimes(self) -> List[PistonRuntime]:
        if self._runtimes_cache is not None:
            return self._runtimes_cache

        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/api/v2/runtimes")
            response.raise_for_status()
            data = response.json()
            self._runtimes_cache = [PistonRuntime(**r) for r in data]
            return self._runtimes_cache
        except Exception as e:
            logger.error(f"Failed to fetch Piston runtimes: {e}")
            return []

    async def is_runtime_available(self, language: str, version: str = "") -> bool:
        runtimes = await self.get_runtimes()
        for runtime in runtimes:
            if runtime.language == language:
                if not version or runtime.version == version:
                    return True
                if version in runtime.aliases:
                    return True
        return False

    async def get_runtime_for_language(self, language: str) -> Optional[PistonRuntime]:
        runtimes = await self.get_runtimes()
        for runtime in runtimes:
            if runtime.language == language:
                return runtime
            if language in runtime.aliases:
                return runtime
        return None

    async def execute(self, request: PistonRunRequest) -> PistonExecuteResponse:
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/api/v2/execute",
                json=request.model_dump(exclude_none=True),
            )

            if response.status_code == 404:
                raise RuntimeUnavailableError(request.language)

            if response.status_code == 413:
                raise ExecutionLimitError("Request payload too large")

            if response.status_code == 408 or response.status_code == 504:
                raise ExecutionTimeoutError()

            response.raise_for_status()
            return PistonExecuteResponse(**response.json())

        except httpx.TimeoutException:
            raise ExecutionTimeoutError()
        except httpx.ConnectError as e:
            logger.error(f"Piston connection error: {e}")
            raise PistonUnavailableError("Cannot connect to Piston service")
        except PistonUnavailableError:
            raise
        except RuntimeUnavailableError:
            raise
        except ExecutionTimeoutError:
            raise
        except ExecutionLimitError:
            raise
        except Exception as e:
            logger.error(f"Piston execution error: {e}")
            if hasattr(e, "response") and e.response is not None:
                raise PistonAPIError(e.response.status_code, e.response.text)
            raise PistonAPIError(500, str(e))

    async def execute_code(
        self,
        language: str,
        code: str,
        files: Optional[List[dict]] = None,
        stdin: str = "",
        args: Optional[List[str]] = None,
        compile_timeout: int = 10000,
        run_timeout: int = 10000,
        memory_limit_mb: Optional[int] = None,
        cpu_limit: Optional[float] = None,
        packages: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> PistonExecuteResponse:
        """Execute code with resource limits and package management."""
        if files is None:
            files = [{"name": "main", "content": code}]

        # Apply resource limits and package management
        memory_limit = memory_limit_mb or self.default_memory_limit
        cpu_limit = cpu_limit or self.default_cpu_limit
        
        # Add packages for the language if specified
        if packages:
            for file in files:
                if "packages" not in file:
                    file["packages"] = packages
        
        # Add environment variables
        if env_vars:
            for file in files:
                if "env" not in file:
                    file["env"] = env_vars

        request = PistonRunRequest(
            language=language,
            files=[{"name": f["name"], "content": f["content"]} for f in files],
            stdin=stdin,
            args=args or [],
            compile_timeout=compile_timeout,
            run_timeout=run_timeout,
            # Resource limits (Piston v2+ supports these)
            memory_limit=f"{memory_limit}m",
            cpu_limit=cpu_limit,
        )

        return await self.execute(request)

    async def install_packages(self, language: str, packages: List[str]) -> Dict[str, Any]:
        """Install packages for a specific language runtime."""
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/api/v2/packages",
                json={"language": language, "packages": packages},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to install packages for {language}: {e}")
            raise PistonAPIError(500, f"Package installation failed: {str(e)}")

    async def get_package_list(self, language: str) -> List[str]:
        """Get available packages for a language."""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/api/v2/packages/{language}")
            response.raise_for_status()
            return response.json()
        except Exception:
            return []


piston_client = PistonClient()