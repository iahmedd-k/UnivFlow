from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.services.code_executor import code_executor
from app.execution import (
    ExecutionStatus,
    ExecutionType,
    UnsupportedLanguageError,
    resolve_language,
    get_all_languages,
    get_execution_backend,
    get_execution_type,
)

router = APIRouter(prefix="/execution", tags=["Execution"])


class ExecuteRequest(BaseModel):
    language: str = Field(..., description="Programming language or database type")
    code: str = Field(..., description="Source code or query to execute")
    files: Optional[List[Dict[str, str]]] = Field(default=None, description="Additional files for multi-file programs")
    stdin: str = Field(default="", description="Standard input for the program")
    args: Optional[List[str]] = Field(default=None, description="Command line arguments")
    max_attempts: Optional[int] = Field(default=None, description="Maximum retry attempts")


class ExecuteResponse(BaseModel):
    success: bool
    execution_id: str
    execution_type: str
    language: str
    stdout: str = ""
    stderr: str = ""
    output: str = ""
    exit_code: Optional[int] = None
    signal: Optional[str] = None
    timed_out: bool = False
    execution_time: float = 0.0
    attempt: int = 1
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    affected_rows: Optional[int] = None
    database_type: Optional[str] = None
    database_name: Optional[str] = None


class LanguageInfo(BaseModel):
    id: str
    display_name: str
    aliases: List[str]
    execution_type: str
    backend: str
    runtime: str = ""


class LanguagesResponse(BaseModel):
    languages: List[LanguageInfo]
    by_type: Dict[str, List[str]]


class HealthResponse(BaseModel):
    healthy: bool
    checks: Dict[str, bool]


@router.post("/execute", response_model=ExecuteResponse)
async def execute_code(request: ExecuteRequest):
    try:
        resolve_language(request.language)
    except UnsupportedLanguageError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await code_executor.execute_with_retry(
        language=request.language,
        code=request.code,
        files=request.files,
        stdin=request.stdin,
        args=request.args,
        max_attempts=request.max_attempts,
    )

    if hasattr(result, 'columns'):
        return ExecuteResponse(
            success=result.success,
            execution_id=result.execution_id,
            execution_type="database",
            language=request.language,
            columns=result.columns,
            rows=result.rows,
            affected_rows=result.affected_rows,
            stdout=result.stdout,
            stderr=result.stderr,
            execution_time=result.execution_time,
            error_type=result.error_type,
            error_message=result.error_message,
            database_type=result.database_type.value if result.database_type else None,
            database_name=result.database_name,
        )
    else:
        return ExecuteResponse(
            success=result.success,
            execution_id=result.execution_id,
            execution_type=result.execution_type.value,
            language=result.language,
            stdout=result.stdout,
            stderr=result.stderr,
            output=result.output,
            exit_code=result.exit_code,
            signal=result.signal,
            timed_out=result.timed_out,
            execution_time=result.execution_time,
            attempt=result.attempt,
            error_type=result.error_type,
            error_message=result.error_message,
        )


@router.get("/languages", response_model=LanguagesResponse)
async def get_languages():
    languages = get_all_languages()
    language_infos = [
        LanguageInfo(
            id=lang.id,
            display_name=lang.display_name,
            aliases=lang.aliases,
            execution_type=lang.execution_type.value,
            backend=lang.backend.value,
            runtime=lang.runtime,
        )
        for lang in languages
    ]

    by_type = {
        "programming": [l.id for l in languages if l.execution_type == ExecutionType.PROGRAMMING],
        "database": [l.id for l in languages if l.execution_type == ExecutionType.DATABASE],
    }

    return LanguagesResponse(languages=language_infos, by_type=by_type)


@router.get("/health", response_model=HealthResponse)
async def execution_health():
    health = await code_executor.health_check()
    return HealthResponse(healthy=health["healthy"], checks=health["checks"])


@router.get("/languages/{language_id}")
async def get_language_info(language_id: str):
    try:
        config = resolve_language(language_id)
    except UnsupportedLanguageError:
        raise HTTPException(status_code=404, detail=f"Language '{language_id}' not found")

    return {
        "id": config.id,
        "display_name": config.display_name,
        "aliases": config.aliases,
        "execution_type": config.execution_type.value,
        "backend": config.backend.value,
        "runtime": config.runtime,
    }