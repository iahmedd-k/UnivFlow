class KrokiException(Exception):
    def __init__(self, message: str, error_code: str = "KROKI_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class KrokiUnavailableError(KrokiException):
    def __init__(self, message: str = "Kroki service is unavailable"):
        super().__init__(message, "KROKI_UNAVAILABLE")


class DiagramRenderError(KrokiException):
    def __init__(self, message: str, details: str = ""):
        super().__init__(message, "DIAGRAM_RENDER_ERROR")
        self.details = details


class DiagramTimeoutError(KrokiException):
    def __init__(self, message: str = "Diagram rendering timed out"):
        super().__init__(message, "DIAGRAM_TIMEOUT")


class DiagramSizeLimitError(KrokiException):
    def __init__(self, message: str = "Diagram source exceeds size limit"):
        super().__init__(message, "DIAGRAM_SIZE_LIMIT")


class UnsupportedDiagramTypeError(KrokiException):
    def __init__(self, diagram_type: str):
        super().__init__(f"Unsupported diagram type: {diagram_type}", "UNSUPPORTED_DIAGRAM_TYPE")


class UnsupportedOutputFormatError(KrokiException):
    def __init__(self, format: str):
        super().__init__(f"Unsupported output format: {format}", "UNSUPPORTED_OUTPUT_FORMAT")


class KrokiAPIError(KrokiException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Kroki API error ({status_code}): {detail}", "KROKI_API_ERROR")
        self.status_code = status_code
        self.detail = detail