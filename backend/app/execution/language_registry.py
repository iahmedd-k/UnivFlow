from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from app.execution.models import ExecutionType, DatabaseType


class ExecutionBackend(str, Enum):
    PISTON = "piston"
    SQLITE = "sqlite"
    MYSQL = "mysql"
    MONGODB = "mongodb"


@dataclass
class LanguageConfig:
    id: str
    display_name: str
    aliases: List[str]
    execution_type: ExecutionType
    backend: ExecutionBackend
    runtime: str = ""
    version: str = ""


LANGUAGE_REGISTRY: Dict[str, LanguageConfig] = {
    # Programming Languages - Piston
    "python": LanguageConfig(
        id="python",
        display_name="Python",
        aliases=["py", "python3"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="python",
    ),
    "javascript": LanguageConfig(
        id="javascript",
        display_name="JavaScript",
        aliases=["js", "node", "nodejs"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="javascript",
    ),
    "typescript": LanguageConfig(
        id="typescript",
        display_name="TypeScript",
        aliases=["ts"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="typescript",
    ),
    "c": LanguageConfig(
        id="c",
        display_name="C",
        aliases=["gcc"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="c",
    ),
    "cpp": LanguageConfig(
        id="cpp",
        display_name="C++",
        aliases=["c++"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="cpp",
    ),
    "java": LanguageConfig(
        id="java",
        display_name="Java",
        aliases=["openjdk"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="java",
    ),
    "go": LanguageConfig(
        id="go",
        display_name="Go",
        aliases=["golang"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="go",
    ),
    "assembly": LanguageConfig(
        id="assembly",
        display_name="Assembly (NASM)",
        aliases=["asm", "nasm"],
        execution_type=ExecutionType.PROGRAMMING,
        backend=ExecutionBackend.PISTON,
        runtime="nasm",
    ),
    # Database Languages
    "sqlite": LanguageConfig(
        id="sqlite",
        display_name="SQLite",
        aliases=["sql", "sqlite3"],
        execution_type=ExecutionType.DATABASE,
        backend=ExecutionBackend.SQLITE,
    ),
    "mysql": LanguageConfig(
        id="mysql",
        display_name="MySQL",
        aliases=["sql-mysql"],
        execution_type=ExecutionType.DATABASE,
        backend=ExecutionBackend.MYSQL,
    ),
    "mongodb": LanguageConfig(
        id="mongodb",
        display_name="MongoDB",
        aliases=["mongo", "nosql"],
        execution_type=ExecutionType.DATABASE,
        backend=ExecutionBackend.MONGODB,
    ),
}


def get_language_config(language_id: str) -> Optional[LanguageConfig]:
    return LANGUAGE_REGISTRY.get(language_id)


def get_all_languages() -> List[LanguageConfig]:
    return list(LANGUAGE_REGISTRY.values())


def get_languages_by_type(execution_type: ExecutionType) -> List[LanguageConfig]:
    return [lang for lang in LANGUAGE_REGISTRY.values() if lang.execution_type == execution_type]


def get_languages_by_backend(backend: ExecutionBackend) -> List[LanguageConfig]:
    return [lang for lang in LANGUAGE_REGISTRY.values() if lang.backend == backend]