import logging
from typing import Any, Dict, List, Optional, Union

from app.v1.models import (
    ExecutionResult,
    DatabaseExecutionResult,
    ExecutionStatus,
    ExecutionType,
    DatabaseType,
)
from app.execution import (
    resolve_language,
    UnsupportedLanguageError,
    get_execution_type,
)
from app.execution.programming.piston_executor import PistonExecutor
from app.execution.database.sqlite_executor import SQLiteExecutor
from app.execution.database.mysql_executor import MySQLExecutor
from app.execution.database.mongodb_executor import MongoDBExecutor
from app.core.config import settings

logger = logging.getLogger(__name__)


class CodeExecutor:
    def __init__(self):
        self._programming_executor = PistonExecutor()
        self._sqlite_executor = SQLiteExecutor()
        self._mysql_executor: Optional[MySQLExecutor] = None
        self._mongodb_executor: Optional[MongoDBExecutor] = None

        self._init_database_executors()

    def _init_database_executors(self):
        try:
            if all([settings.mysql_host, settings.mysql_database, settings.mysql_user]):
                self._mysql_executor = MySQLExecutor()
                logger.info("MySQL executor initialized")
        except Exception as e:
            logger.warning(f"MySQL executor not available: {e}")

        try:
            if settings.mongodb_uri and settings.mongodb_database:
                self._mongodb_executor = MongoDBExecutor()
                logger.info("MongoDB executor initialized")
        except Exception as e:
            logger.warning(f"MongoDB executor not available: {e}")

    async def execute(
        self,
        language: str,
        code: str,
        files: Optional[List[Dict[str, str]]] = None,
        stdin: str = "",
        args: Optional[List[str]] = None,
        attempt: int = 1,
    ) -> Union[ExecutionResult, DatabaseExecutionResult]:
        try:
            config = resolve_language(language)
        except UnsupportedLanguageError as e:
            logger.warning(f"Unsupported language: {language}")
            return ExecutionResult.error_result(
                language=language,
                error_type="UnsupportedLanguageError",
                error_message=str(e),
                status=ExecutionStatus.UNSUPPORTED_LANGUAGE,
                attempt=attempt,
            )

        execution_type = config.execution_type

        if execution_type == ExecutionType.PROGRAMMING:
            return await self._execute_programming(config, code, files, stdin, args, attempt)
        elif execution_type == ExecutionType.DATABASE:
            return await self._execute_database(config, code, attempt)
        else:
            return ExecutionResult.error_result(
                language=language,
                error_type="InvalidExecutionTypeError",
                error_message=f"Unknown execution type: {execution_type}",
                status=ExecutionStatus.ERROR,
                attempt=attempt,
            )

    async def _execute_programming(
        self,
        config,
        code: str,
        files: Optional[List[Dict[str, str]]],
        stdin: str,
        args: Optional[List[str]],
        attempt: int,
    ) -> ExecutionResult:
        if not files and len(code.encode("utf-8")) > settings.code_execution_max_code_bytes:
            return ExecutionResult.error_result(
                language=config.id,
                error_type="ExecutionLimitError",
                error_message=f"Code size exceeds maximum allowed ({settings.code_execution_max_code_bytes} bytes)",
                status=ExecutionStatus.LIMIT_EXCEEDED,
                attempt=attempt,
            )

        from app.execution.base import ExecutionRequest
        request = ExecutionRequest(
            language=config.id,
            code=code,
            files=files,
            stdin=stdin,
            args=args,
            attempt=attempt,
        )

        result = await self._programming_executor.execute(request)

        if result.stdout and len(result.stdout.encode("utf-8")) > settings.code_execution_max_output_bytes:
            result.stdout = result.stdout[:settings.code_execution_max_output_bytes] + "\n[OUTPUT TRUNCATED]"
            result.output = result.output[:settings.code_execution_max_output_bytes] + "\n[OUTPUT TRUNCATED]"

        return result

    async def _execute_database(self, config, query: str, attempt: int) -> DatabaseExecutionResult:
        executor = self._get_database_executor(config.backend.value)

        if not executor:
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.BACKEND_UNAVAILABLE,
                database_type=DatabaseType(config.id),
                database_name="",
                error_type="BackendUnavailableError",
                error_message=f"Database executor for {config.id} is not configured",
            )

        from app.execution.base import DatabaseExecutionRequest
        request = DatabaseExecutionRequest(
            database_type=DatabaseType(config.id),
            query=query,
        )

        return await executor.execute(request)

    def _get_database_executor(self, backend: str):
        if backend == "sqlite":
            return self._sqlite_executor
        elif backend == "mysql":
            return self._mysql_executor
        elif backend == "mongodb":
            return self._mongodb_executor
        return None

    async def execute_with_retry(
        self,
        language: str,
        code: str,
        files: Optional[List[Dict[str, str]]] = None,
        stdin: str = "",
        args: Optional[List[str]] = None,
        max_attempts: int = None,
    ) -> Union[ExecutionResult, DatabaseExecutionResult]:
        max_attempts = max_attempts or settings.code_execution_max_attempts

        last_result = None
        for attempt in range(1, max_attempts + 1):
            result = await self.execute(
                language=language,
                code=code,
                files=files,
                stdin=stdin,
                args=args,
                attempt=attempt,
            )
            last_result = result

            if isinstance(result, ExecutionResult) and result.success:
                break

            if isinstance(result, DatabaseExecutionResult) and result.success:
                break

            if attempt < max_attempts:
                logger.info(f"Execution attempt {attempt} failed for {language}, retrying...")

        return last_result

    async def health_check(self) -> Dict[str, Any]:
        checks = {
            "piston": await self._programming_executor.health_check(),
            "sqlite": await self._sqlite_executor.health_check(),
        }

        if self._mysql_executor:
            checks["mysql"] = await self._mysql_executor.health_check()

        if self._mongodb_executor:
            checks["mongodb"] = await self._mongodb_executor.health_check()

        all_healthy = all(checks.values())

        return {
            "healthy": all_healthy,
            "checks": checks,
        }

    def get_supported_languages(self) -> Dict[str, List[str]]:
        return {
            "programming": self._programming_executor.supported_languages,
            "database": ["sqlite"] + (["mysql"] if self._mysql_executor else []) + (["mongodb"] if self._mongodb_executor else []),
        }


code_executor = CodeExecutor()