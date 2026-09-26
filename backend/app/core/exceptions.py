class StudyPilotException(Exception):
    def __init__(self, message: str, error_code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class AuthError(StudyPilotException):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTH_ERROR")


class RateLimitError(StudyPilotException):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, "RATE_LIMIT")


class NetworkError(StudyPilotException):
    def __init__(self, message: str = "Network error"):
        super().__init__(message, "NETWORK_ERROR")


class SourceError(StudyPilotException):
    def __init__(self, message: str = "Data source error"):
        super().__init__(message, "SOURCE_ERROR")


class ValidationError(StudyPilotException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, "VALIDATION_ERROR")


class AIError(StudyPilotException):
    def __init__(self, message: str = "AI processing error"):
        super().__init__(message, "AI_ERROR")


class DocumentError(StudyPilotException):
    def __init__(self, message: str = "Document generation error"):
        super().__init__(message, "DOCUMENT_ERROR")


class SubmissionError(StudyPilotException):
    def __init__(self, message: str = "Submission error"):
        super().__init__(message, "SUBMISSION_ERROR")


class PortalAuthError(StudyPilotException):
    def __init__(self, message: str = "University portal authentication failed"):
        super().__init__(message, "AUTH_FAILED")