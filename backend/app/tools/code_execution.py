from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.services.code_executor import code_executor


class ExecuteCodeRequest(BaseModel):
    language: str = Field(..., description="Programming language or database type (e.g., python, javascript, sqlite, mysql, mongodb)")
    code: str = Field(..., description="Source code or query to execute")
    files: Optional[List[Dict[str, str]]] = Field(default=None, description="Optional additional files for multi-file programs")
    stdin: str = Field(default="", description="Standard input for the program")
    args: Optional[List[str]] = Field(default=None, description="Command line arguments")
    max_attempts: Optional[int] = Field(default=None, description="Maximum retry attempts (default from config)")


class ExecuteCodeResponse(BaseModel):
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


async def execute_code(request: ExecuteCodeRequest) -> ExecuteCodeResponse:
    result = await code_executor.execute_with_retry(
        language=request.language,
        code=request.code,
        files=request.files,
        stdin=request.stdin,
        args=request.args,
        max_attempts=request.max_attempts,
    )

    if hasattr(result, 'columns'):
        return ExecuteCodeResponse(
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
        return ExecuteCodeResponse(
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


def get_execute_code_tool_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute code in a programming language or run database queries. Supports Python, JavaScript, TypeScript, C, C++, Java, Go, Assembly (NASM), SQLite, MySQL, and MongoDB.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language or database type: python, javascript, typescript, c, cpp, java, go, assembly, sqlite, mysql, mongodb",
                    },
                    "code": {
                        "type": "string",
                        "description": "Source code or query to execute",
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["name", "content"],
                        },
                        "description": "Additional files for multi-file programs",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "Standard input for the program",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command line arguments",
                    },
                    "max_attempts": {
                        "type": "integer",
                        "description": "Maximum retry attempts",
                    },
                },
                "required": ["language", "code"],
            },
        },
    }


async def handle_execute_code_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    request = ExecuteCodeRequest(**arguments)
    response = await execute_code(request)
    return response.model_dump()