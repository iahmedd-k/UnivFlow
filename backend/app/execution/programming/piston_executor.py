import time
import logging
from typing import List, Optional, Dict, Any

from app.execution.base import BaseExecutor, ExecutionRequest
from app.execution.models import (
    ExecutionResult,
    ExecutionStatus,
    ExecutionType,
)
from app.execution.language_registry import LANGUAGE_REGISTRY, ExecutionBackend
from app.integrations.piston import piston_client, PistonUnavailableError, RuntimeUnavailableError, ExecutionTimeoutError, ExecutionLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)

# Language-specific default packages
LANGUAGE_PACKAGES = {
    "python": ["numpy", "pandas", "requests", "matplotlib", "scipy", "sklearn"],
    "javascript": ["lodash", "axios", "express"],
    "typescript": ["@types/node", "axios"],
    "java": [],
    "cpp": [],
    "c": [],
    "go": [],
    "rust": [],
}


class PistonExecutor(BaseExecutor):
    def __init__(self):
        self._client = piston_client

    @property
    def execution_type(self) -> ExecutionType:
        return ExecutionType.PROGRAMMING

    @property
    def supported_languages(self) -> List[str]:
        return [
            lang_id
            for lang_id, config in LANGUAGE_REGISTRY.items()
            if config.backend == ExecutionBackend.PISTON
        ]

    def _get_packages_for_language(self, language: str, request_packages: Optional[List[str]] = None) -> List[str]:
        """Get packages to install for the language."""
        packages = []
        if request_packages:
            packages.extend(request_packages)
        if language in LANGUAGE_PACKAGES:
            packages.extend(LANGUAGE_PACKAGES[language])
        return packages

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        start_time = time.perf_counter()
        language = request.language

        config = LANGUAGE_REGISTRY.get(language)
        if not config:
            return ExecutionResult.error_result(
                language=language,
                error_type="UnsupportedLanguageError",
                error_message=f"Language '{language}' is not configured for Piston execution",
                status=ExecutionStatus.UNSUPPORTED_LANGUAGE,
                attempt=request.attempt,
            )

        runtime = config.runtime

        try:
            if request.files:
                files = request.files
            else:
                extension = self._get_file_extension(language)
                files = [{"name": f"main.{extension}", "content": request.code}]

            compile_timeout = min(settings.code_execution_timeout_seconds * 1000, 30000)
            run_timeout = min(settings.code_execution_timeout_seconds * 1000, 30000)

            # Get packages for this language
            packages = self._get_packages_for_language(language, getattr(request, 'packages', None))

            piston_response = await self._client.execute_code(
                language=runtime,
                code=request.code,
                files=files,
                stdin=request.stdin,
                args=request.args,
                compile_timeout=compile_timeout,
                run_timeout=run_timeout,
                memory_limit_mb=getattr(settings, 'piston_memory_limit_mb', 256),
                cpu_limit=getattr(settings, 'piston_cpu_limit', 1.0),
                packages=packages,
            )

            execution_time = time.perf_counter() - start_time
            return ExecutionResult.from_piston(
                piston_response=piston_response,
                language=language,
                runtime=runtime,
                execution_time=execution_time,
                attempt=request.attempt,
            )

        except PistonUnavailableError as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"Piston unavailable: {e}")
            return ExecutionResult.error_result(
                language=language,
                error_type="PistonUnavailableError",
                error_message=str(e),
                status=ExecutionStatus.BACKEND_UNAVAILABLE,
                attempt=request.attempt,
                execution_time=execution_time,
            )

        except RuntimeUnavailableError as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"Runtime unavailable: {e}")
            return ExecutionResult.error_result(
                language=language,
                error_type="RuntimeUnavailableError",
                error_message=str(e),
                status=ExecutionStatus.UNSUPPORTED_LANGUAGE,
                attempt=request.attempt,
                execution_time=execution_time,
            )

        except ExecutionTimeoutError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Execution timeout: {e}")
            return ExecutionResult.error_result(
                language=language,
                error_type="ExecutionTimeoutError",
                error_message="Code execution timed out",
                status=ExecutionStatus.TIMEOUT,
                attempt=request.attempt,
                execution_time=execution_time,
            )

        except ExecutionLimitError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"Execution limit exceeded: {e}")
            return ExecutionResult.error_result(
                language=language,
                error_type="ExecutionLimitError",
                error_message=str(e),
                status=ExecutionStatus.LIMIT_EXCEEDED,
                attempt=request.attempt,
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"Piston execution error: {e}")
            return ExecutionResult.error_result(
                language=language,
                error_type="ExecutionError",
                error_message=str(e),
                status=ExecutionStatus.ERROR,
                attempt=request.attempt,
                execution_time=execution_time,
            )

    async def health_check(self) -> bool:
        try:
            await self._client.health_check()
            return True
        except Exception:
            return False

    def _get_file_extension(self, language: str) -> str:
        extensions = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "c": "c",
            "cpp": "cpp",
            "java": "java",
            "go": "go",
            "assembly": "asm",
            "rust": "rs",
            "csharp": "cs",
            "php": "php",
            "ruby": "rb",
            "swift": "swift",
            "kotlin": "kt",
            "scala": "scala",
            "r": "r",
            "dart": "dart",
            "perl": "pl",
            "lua": "lua",
            "haskell": "hs",
            "ocaml": "ml",
            "fsharp": "fs",
            "clojure": "clj",
            "elixir": "ex",
            "erlang": "erl",
            "julia": "jl",
            "nim": "nim",
            "zig": "zig",
            "vlang": "v",
            "dart": "dart",
            "solidity": "sol",
            "vue": "vue",
            "svelte": "svelte",
        }
        return extensions.get(language, "txt")