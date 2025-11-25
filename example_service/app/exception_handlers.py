"""Global exception handlers for FastAPI application."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from example_service.core.exceptions import AppException, RateLimitException
from example_service.core.schemas.error import (
    ProblemDetail,
    ValidationError,
    ValidationProblemDetail,
)
from example_service.infra.metrics import tracking

logger = logging.getLogger(__name__)


def _get_request_id(request: Request) -> str | None:
    """Extract request ID from request state.

    Args:
        request: The FastAPI request object.

    Returns:
        Request ID if available, None otherwise.
    """
    return getattr(request.state, "request_id", None)


def _create_problem_detail(
    status_code: int,
    detail: str,
    type_: str = "about:blank",
    title: str | None = None,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create RFC 7807 Problem Details response.

    Args:
        status_code: HTTP status code.
        detail: Human-readable error description.
        type_: Error type identifier.
        title: Short human-readable summary.
        instance: URI identifying this occurrence.
        extra: Additional context information.

    Returns:
        Dictionary representing the problem detail.
    """
    problem = ProblemDetail(
        type=type_,
        title=title or ProblemDetail._default_title(status_code),
        status=status_code,
        detail=detail,
        instance=instance,
    )

    # Convert to dict and add extra fields
    response_data = problem.model_dump(exclude_none=True)
    if extra:
        response_data.update(extra)

    return response_data


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application exceptions.

    This handler converts our custom AppException instances into
    RFC 7807 Problem Details responses.

    Args:
        request: The FastAPI request object.
        exc: The application exception that was raised.

    Returns:
        JSONResponse with RFC 7807 Problem Details format.
    """
    request_id = _get_request_id(request)

    # Track error metric
    tracking.track_error(
        error_type=exc.type,
        endpoint=request.url.path,
        status_code=exc.status_code,
        extra={"detail": exc.detail},
    )

    # Log the exception with context
    logger.warning(
        "Application exception occurred",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "exception_type": exc.type,
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
    )

    # Create RFC 7807 problem detail response
    problem_data = _create_problem_detail(
        status_code=exc.status_code,
        detail=exc.detail,
        type_=exc.type,
        title=exc.title,
        instance=exc.instance or str(request.url),
        extra=exc.extra,
    )

    # Add request ID if available
    if request_id:
        problem_data["request_id"] = request_id

    # Add Retry-After header for rate limit exceptions
    headers = {}
    if isinstance(exc, RateLimitException) and "retry_after" in exc.extra:
        headers["Retry-After"] = str(exc.extra["retry_after"])

    return JSONResponse(
        status_code=exc.status_code,
        content=problem_data,
        headers=headers if headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI/Pydantic validation errors.

    This handler converts validation errors into RFC 7807 Problem Details
    format with field-level error information.

    Args:
        request: The FastAPI request object.
        exc: The validation error that was raised.

    Returns:
        JSONResponse with RFC 7807 Problem Details format.
    """
    request_id = _get_request_id(request)

    # Extract validation errors
    validation_errors = []
    for error in exc.errors():
        field_path = ".".join(str(loc) for loc in error["loc"])
        validation_errors.append(
            ValidationError(
                field=field_path,
                message=error["msg"],
                type=error["type"],
                value=error.get("input"),
            )
        )
        # Track each validation error
        tracking.track_validation_error(request.url.path, field_path)

    # Log validation error
    logger.warning(
        "Request validation failed",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "error_count": len(validation_errors),
            "errors": [e.model_dump() for e in validation_errors],
        },
    )

    # Create validation problem detail
    problem = ValidationProblemDetail(
        type="validation-error",
        title="Validation Error",
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Request validation failed for {len(validation_errors)} field(s)",
        instance=str(request.url),
        errors=validation_errors,
    )

    response_data = problem.model_dump(exclude_none=True)
    if request_id:
        response_data["request_id"] = request_id

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_data,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions.

    This is the catch-all handler for exceptions that don't have
    specific handlers. It logs the full traceback and returns a
    generic 500 error to the client.

    Args:
        request: The FastAPI request object.
        exc: The exception that was raised.

    Returns:
        JSONResponse with RFC 7807 Problem Details format.
    """
    request_id = _get_request_id(request)

    # Track unhandled exception
    tracking.track_unhandled_exception(
        exception_type=type(exc).__name__,
        endpoint=request.url.path,
    )

    # Log the exception with full traceback
    logger.error(
        "Unexpected exception occurred",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        },
        exc_info=True,
    )

    # Create generic error response
    # Don't expose internal details in production
    problem_data = _create_problem_detail(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred while processing your request",
        type_="internal-error",
        title="Internal Server Error",
        instance=str(request.url),
    )

    if request_id:
        problem_data["request_id"] = request_id

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=problem_data,
    )


async def pydantic_validation_exception_handler(
    request: Request, exc: PydanticValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors outside of FastAPI request validation.

    Args:
        request: The FastAPI request object.
        exc: The Pydantic validation error that was raised.

    Returns:
        JSONResponse with RFC 7807 Problem Details format.
    """
    request_id = _get_request_id(request)

    # Extract validation errors
    validation_errors = []
    for error in exc.errors():
        field_path = ".".join(str(loc) for loc in error["loc"])
        validation_errors.append(
            ValidationError(
                field=field_path,
                message=error["msg"],
                type=error["type"],
                value=error.get("input"),
            )
        )

    # Log validation error
    logger.warning(
        "Pydantic validation failed",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "error_count": len(validation_errors),
        },
    )

    # Create validation problem detail
    problem = ValidationProblemDetail(
        type="validation-error",
        title="Validation Error",
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Data validation failed for {len(validation_errors)} field(s)",
        instance=str(request.url),
        errors=validation_errors,
    )

    response_data = problem.model_dump(exclude_none=True)
    if request_id:
        response_data["request_id"] = request_id

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_data,
    )


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure exception handlers for the FastAPI application.

    This function registers all custom exception handlers that convert
    exceptions into RFC 7807 Problem Details responses.

    Args:
        app: The FastAPI application instance.

    Example:
            app = FastAPI()
        configure_exception_handlers(app)
    """
    # Custom application exceptions
    app.add_exception_handler(AppException, app_exception_handler)

    # FastAPI validation errors
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # Pydantic validation errors
    app.add_exception_handler(PydanticValidationError, pydantic_validation_exception_handler)

    # Catch-all for unexpected exceptions
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Exception handlers configured")


# Helper function to get default title from status code
ProblemDetail._default_title = lambda status_code: {
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
}.get(status_code, "Error")
