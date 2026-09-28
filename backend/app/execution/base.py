from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from app.execution.models import (
    ExecutionResult,
    DatabaseExecutionResult,
    ExecutionStatus,
    ExecutionType,
    DatabaseType,
)


@dataclass
class ExecutionRequest:
    language: str
    code: str
    files: Optional[List[Dict[str, str]]] = None
    stdin: str = ""
    args: Optional[List[str]] = None
    attempt: int = 1


@dataclass
class DatabaseExecutionRequest:
    database_type: DatabaseType
    query: str
    database_name: str = ""
    params: Optional[List[Any]] = None


class BaseExecutor(ABC):
    @property
    @abstractmethod
    def execution_type(self) -> ExecutionType:
        pass

    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        pass

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass


class BaseDatabaseExecutor(ABC):
    @property
    @abstractmethod
    def database_type(self) -> DatabaseType:
        pass

    @abstractmethod
    async def execute(self, request: DatabaseExecutionRequest) -> DatabaseExecutionResult:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass