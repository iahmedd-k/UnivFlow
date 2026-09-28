import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    LIMIT_EXCEEDED = "limit_exceeded"


class ExecutionType(str, Enum):
    PROGRAMMING = "programming"
    DATABASE = "database"


class DatabaseType(str, Enum):
    SQLITE = "sqlite"
    MYSQL = "mysql"
    MONGODB = "mongodb"


@dataclass
class ExecutionResult:
    execution_id: str = field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:8]}")
    success: bool = False
    status: ExecutionStatus = ExecutionStatus.ERROR
    execution_type: ExecutionType = ExecutionType.PROGRAMMING

    language: str = ""
    version: str = ""
    runtime: str = ""

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

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "success": self.success,
            "status": self.status.value,
            "execution_type": self.execution_type.value,
            "language": self.language,
            "version": self.version,
            "runtime": self.runtime,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output": self.output,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "timed_out": self.timed_out,
            "execution_time": self.execution_time,
            "attempt": self.attempt,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_piston(cls, piston_response, language: str, runtime: str, execution_time: float, attempt: int = 1) -> "ExecutionResult":
        run = piston_response.run
        compile_output = piston_response.compile

        stdout = run.stdout or ""
        stderr = run.stderr or ""
        output = run.output or ""
        exit_code = run.code
        signal = run.signal
        timed_out = signal == "SIGKILL" or (exit_code == 124)

        success = exit_code == 0 and not timed_out

        if compile_output and compile_output.code != 0:
            success = False
            stderr = (compile_output.stderr or compile_output.output or "") + "\n" + stderr

        if timed_out:
            status = ExecutionStatus.TIMEOUT
            error_type = "ExecutionTimeoutError"
            error_message = "Code execution timed out"
        elif not success:
            status = ExecutionStatus.ERROR
            error_type = "ExecutionError"
            error_message = stderr or "Execution failed"
        else:
            status = ExecutionStatus.SUCCESS
            error_type = None
            error_message = None

        return cls(
            success=success,
            status=status,
            execution_type=ExecutionType.PROGRAMMING,
            language=language,
            version=piston_response.version,
            runtime=runtime,
            stdout=stdout,
            stderr=stderr,
            output=output,
            exit_code=exit_code,
            signal=signal,
            timed_out=timed_out,
            execution_time=execution_time,
            attempt=attempt,
            error_type=error_type,
            error_message=error_message,
        )

    @classmethod
    def error_result(
        cls,
        language: str,
        error_type: str,
        error_message: str,
        status: ExecutionStatus = ExecutionStatus.ERROR,
        attempt: int = 1,
        execution_time: float = 0.0,
    ) -> "ExecutionResult":
        return cls(
            success=False,
            status=status,
            execution_type=ExecutionType.PROGRAMMING,
            language=language,
            error_type=error_type,
            error_message=error_message,
            attempt=attempt,
            execution_time=execution_time,
        )


@dataclass
class DatabaseExecutionResult:
    execution_id: str = field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:8]}")
    success: bool = False
    status: ExecutionStatus = ExecutionStatus.ERROR

    database_type: DatabaseType = DatabaseType.SQLITE
    database_name: str = ""

    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    affected_rows: int = 0

    stdout: str = ""
    stderr: str = ""

    execution_time: float = 0.0

    error_type: Optional[str] = None
    error_message: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "success": self.success,
            "status": self.status.value,
            "database_type": self.database_type.value,
            "database_name": self.database_name,
            "columns": self.columns,
            "rows": self.rows,
            "affected_rows": self.affected_rows,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "execution_time": self.execution_time,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }