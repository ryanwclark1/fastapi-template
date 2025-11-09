"""Custom exception classes for the application."""
from __future__ import annotations


class AppException(Exception):
    """Base application exception.

    All custom exceptions should inherit from this class.

    Attributes:
        status_code: HTTP status code for the error.
        detail: Human-readable error message.
        type: Error type identifier (used in RFC 7807 problem details).

    Example:
        ```python
        raise AppException(
            status_code=404,
            detail="Resource not found",
            type="resource-not-found"
        )
        ```
    """

    def __init__(
        self, status_code: int, detail: str, type: str = "about:blank"
    ) -> None:
        """Initialize application exception.

        Args:
            status_code: HTTP status code.
            detail: Human-readable error message.
            type: Error type identifier.
        """
        self.status_code = status_code
        self.detail = detail
        self.type = type
        super().__init__(detail)


class NotFoundException(AppException):
    """Exception raised when a resource is not found.

    Example:
        ```python
        raise NotFoundException(
            detail="User with ID abc123 not found",
            type="user-not-found"
        )
        ```
    """

    def __init__(self, detail: str, type: str = "not-found") -> None:
        """Initialize not found exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
        """
        super().__init__(status_code=404, detail=detail, type=type)


class ValidationException(AppException):
    """Exception raised for validation errors.

    Example:
        ```python
        raise ValidationException(
            detail="Email address is invalid",
            type="validation-error"
        )
        ```
    """

    def __init__(self, detail: str, type: str = "validation-error") -> None:
        """Initialize validation exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
        """
        super().__init__(status_code=422, detail=detail, type=type)


class UnauthorizedException(AppException):
    """Exception raised for authentication failures.

    Example:
        ```python
        raise UnauthorizedException(
            detail="Invalid credentials",
            type="unauthorized"
        )
        ```
    """

    def __init__(self, detail: str, type: str = "unauthorized") -> None:
        """Initialize unauthorized exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
        """
        super().__init__(status_code=401, detail=detail, type=type)


class ForbiddenException(AppException):
    """Exception raised for authorization failures.

    Example:
        ```python
        raise ForbiddenException(
            detail="Insufficient permissions",
            type="forbidden"
        )
        ```
    """

    def __init__(self, detail: str, type: str = "forbidden") -> None:
        """Initialize forbidden exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
        """
        super().__init__(status_code=403, detail=detail, type=type)


class ConflictException(AppException):
    """Exception raised for resource conflicts.

    Example:
        ```python
        raise ConflictException(
            detail="User with email already exists",
            type="resource-conflict"
        )
        ```
    """

    def __init__(self, detail: str, type: str = "conflict") -> None:
        """Initialize conflict exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
        """
        super().__init__(status_code=409, detail=detail, type=type)
