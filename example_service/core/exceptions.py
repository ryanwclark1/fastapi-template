"""Custom exception classes for the application."""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Base application exception.

    All custom exceptions should inherit from this class.
    Follows RFC 7807 Problem Details for HTTP APIs.

    Attributes:
        status_code: HTTP status code for the error.
        detail: Human-readable error message.
        type: Error type identifier (used in RFC 7807 problem details).
        title: Short, human-readable summary of the problem type.
        instance: URI reference that identifies the specific occurrence of the problem.
        extra: Additional context-specific information about the error.

    Example:
            raise AppException(
            status_code=404,
            detail="Resource not found",
            type="resource-not-found",
            title="Resource Not Found",
            instance="/api/v1/users/abc123",
            extra={"resource_id": "abc123", "resource_type": "user"}
        )
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        type: str = "about:blank",
        title: str | None = None,
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize application exception.

        Args:
            status_code: HTTP status code.
            detail: Human-readable error message.
            type: Error type identifier.
            title: Short summary of the problem type.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        self.status_code = status_code
        self.detail = detail
        self.type = type
        self.title = title or self._default_title(status_code)
        self.instance = instance
        self.extra = extra or {}
        super().__init__(detail)

    @staticmethod
    def _default_title(status_code: int) -> str:
        """Get default title for HTTP status code.

        Args:
            status_code: HTTP status code.

        Returns:
            Human-readable title for the status code.
        """
        titles = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            422: "Unprocessable Entity",
            429: "Too Many Requests",
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
            504: "Gateway Timeout",
        }
        return titles.get(status_code, "Error")


class NotFoundException(AppException):
    """Exception raised when a resource is not found.

    Example:
            raise NotFoundException(
            detail="User with ID abc123 not found",
            type="user-not-found",
            extra={"user_id": "abc123"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "not-found",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize not found exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=404,
            detail=detail,
            type=type,
            title="Not Found",
            instance=instance,
            extra=extra,
        )


class ValidationException(AppException):
    """Exception raised for validation errors.

    Example:
            raise ValidationException(
            detail="Email address is invalid",
            type="validation-error",
            extra={"field": "email", "value": "invalid@"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "validation-error",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize validation exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=422,
            detail=detail,
            type=type,
            title="Validation Error",
            instance=instance,
            extra=extra,
        )


class UnauthorizedException(AppException):
    """Exception raised for authentication failures.

    Example:
            raise UnauthorizedException(
            detail="Invalid credentials",
            type="unauthorized",
            extra={"auth_method": "bearer"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "unauthorized",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize unauthorized exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=401,
            detail=detail,
            type=type,
            title="Unauthorized",
            instance=instance,
            extra=extra,
        )


class ForbiddenException(AppException):
    """Exception raised for authorization failures.

    Example:
            raise ForbiddenException(
            detail="Insufficient permissions",
            type="forbidden",
            extra={"required_permission": "admin", "user_role": "user"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "forbidden",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize forbidden exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=403,
            detail=detail,
            type=type,
            title="Forbidden",
            instance=instance,
            extra=extra,
        )


class ConflictException(AppException):
    """Exception raised for resource conflicts.

    Example:
            raise ConflictException(
            detail="User with email already exists",
            type="resource-conflict",
            extra={"field": "email", "value": "user@example.com"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "conflict",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize conflict exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=409,
            detail=detail,
            type=type,
            title="Conflict",
            instance=instance,
            extra=extra,
        )


class BadRequestException(AppException):
    """Exception raised for malformed requests.

    Example:
            raise BadRequestException(
            detail="Invalid request format",
            type="bad-request",
            extra={"reason": "missing required field"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "bad-request",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize bad request exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=400,
            detail=detail,
            type=type,
            title="Bad Request",
            instance=instance,
            extra=extra,
        )


class RateLimitException(AppException):
    """Exception raised when rate limit is exceeded.

    Example:
            raise RateLimitException(
            detail="Too many requests",
            type="rate-limit-exceeded",
            extra={"retry_after": 60, "limit": 100, "window": "minute"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "rate-limit-exceeded",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
        *,
        status_code: int = 429,
    ) -> None:
        """Initialize rate limit exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error (should include retry_after).
            status_code: Override for HTTP status (defaults to 429).
        """
        super().__init__(
            status_code=status_code,
            detail=detail,
            type=type,
            title="Too Many Requests",
            instance=instance,
            extra=extra,
        )


class ServiceUnavailableException(AppException):
    """Exception raised when a service is temporarily unavailable.

    Example:
            raise ServiceUnavailableException(
            detail="Database is temporarily unavailable",
            type="service-unavailable",
            extra={"service": "postgresql", "retry_after": 30}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "service-unavailable",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize service unavailable exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=503,
            detail=detail,
            type=type,
            title="Service Unavailable",
            instance=instance,
            extra=extra,
        )


class CircuitBreakerOpenException(ServiceUnavailableException):
    """Exception raised when circuit breaker is open.

    Example:
            raise CircuitBreakerOpenException(
            detail="Auth service circuit breaker is open",
            extra={"service": "auth", "failures": 5, "retry_after": 60}
        )
    """

    def __init__(
        self,
        detail: str,
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize circuit breaker open exception.

        Args:
            detail: Human-readable error message.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            detail=detail,
            type="circuit-breaker-open",
            instance=instance,
            extra=extra,
        )


class InternalServerException(AppException):
    """Exception raised for internal server errors.

    Example:
            raise InternalServerException(
            detail="An unexpected error occurred",
            type="internal-error",
            extra={"error_id": "abc123"}
        )
    """

    def __init__(
        self,
        detail: str,
        type: str = "internal-error",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize internal server exception.

        Args:
            detail: Human-readable error message.
            type: Error type identifier.
            instance: URI reference identifying this specific occurrence.
            extra: Additional context about the error.
        """
        super().__init__(
            status_code=500,
            detail=detail,
            type=type,
            title="Internal Server Error",
            instance=instance,
            extra=extra,
        )


# Aliases for convenience/backward compatibility
AuthenticationError = UnauthorizedException
AuthorizationError = ForbiddenException
BackendServiceError = ServiceUnavailableException
BadRequestError = BadRequestException
NotFoundError = NotFoundException
ResourceNotFoundError = NotFoundException
ValidationError = ValidationException


__all__ = [
    "AppException",
    # Aliases
    "AuthenticationError",
    "AuthorizationError",
    "BackendServiceError",
    "BadRequestError",
    "BadRequestException",
    "CircuitBreakerOpenException",
    "ConflictException",
    "ForbiddenException",
    "InternalServerException",
    "NotFoundError",
    "NotFoundException",
    "RateLimitException",
    "ResourceNotFoundError",
    "ServiceUnavailableException",
    "UnauthorizedException",
    "ValidationError",
    "ValidationException",
]
