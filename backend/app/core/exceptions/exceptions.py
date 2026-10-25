from fastapi import status


class AppException(Exception):
    """Base application exception with an HTTP status and detail message."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred"

    def __init__(self, detail: str | None = None, status_code: int | None = None):
        if detail is not None:
            self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found"


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    detail = "Resource already exists"


class ValidationError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = "Validation failed"


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Could not validate credentials"


class ForbiddenError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action"


class BadRequestError(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request"


class ServiceUnavailableError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = "Service temporarily unavailable"
