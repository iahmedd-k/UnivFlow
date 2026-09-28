class PistonException(Exception):
    def __init__(self, message: str, error_code: str = "PISTON_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class PistonUnavailableError(PistonException):
    def __init__(self, message: str = "Piston service is unavailable"):
        super().__init__(message, "PISTON_UNAVAILABLE")


class RuntimeUnavailableError(PistonException):
    def __init__(self, runtime: str):
        super().__init__(f"Runtime '{runtime}' is not available in Piston", "RUNTIME_UNAVAILABLE")


class ExecutionTimeoutError(PistonException):
    def __init__(self, message: str = "Code execution timed out"):
        super().__init__(message, "EXECUTION_TIMEOUT")


class ExecutionLimitError(PistonException):
    def __init__(self, message: str = "Execution limits exceeded"):
        super().__init__(message, "EXECUTION_LIMIT_EXCEEDED")


class PistonAPIError(PistonException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Piston API error ({status_code}): {detail}", "PISTON_API_ERROR")
        self.status_code = status_code
        self.detail = detail