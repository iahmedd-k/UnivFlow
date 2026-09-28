from typing import List, Optional
from pydantic import BaseModel, Field


class PistonRunRequest(BaseModel):
    language: str
    version: str = ""
    files: List["PistonFile"] = Field(default_factory=list)
    stdin: str = ""
    args: List[str] = Field(default_factory=list)
    compile_timeout: int = 10000
    run_timeout: int = 10000
    compile_memory_limit: int = -1
    run_memory_limit: int = -1


class PistonFile(BaseModel):
    name: str
    content: str
    encoding: str = "utf-8"


class PistonCompileOutput(BaseModel):
    code: Optional[int] = None
    signal: Optional[str] = None
    output: str = ""
    stdout: str = ""
    stderr: str = ""


class PistonRunOutput(BaseModel):
    code: Optional[int] = None
    signal: Optional[str] = None
    output: str = ""
    stdout: str = ""
    stderr: str = ""


class PistonExecuteResponse(BaseModel):
    language: str
    version: str
    run: PistonRunOutput
    compile: Optional[PistonCompileOutput] = None


class PistonRuntime(BaseModel):
    language: str
    version: str
    aliases: List[str] = Field(default_factory=list)
    runtime: str


class PistonRuntimesResponse(BaseModel):
    runtimes: List[PistonRuntime]


class PistonHealthResponse(BaseModel):
    status: str
    version: str
    runtimes_count: int