"""GraphQL error handling and production error masking.

This module provides error processing that masks internal errors in production
while logging full details for debugging. It also enhances error responses with
structured error codes for type-safe client handling.

Usage:
    # In schema.py:
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        process_errors=process_graphql_errors,
    )
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING

from graphql import GraphQLError, GraphQLFormattedError

from example_service.core.settings import get_settings

if TYPE_CHECKING:
    from strawberry.types import ExecutionContext

logger = logging.getLogger(__name__)

__all__ = [
    "format_validation_error",
    "is_user_facing_error",
    "mask_internal_error",
    "process_graphql_errors",
]


# ============================================================================
# Error Categories
# ============================================================================


class ErrorCategory:
    """Error categories for classification."""

    VALIDATION = "VALIDATION_ERROR"
    AUTHENTICATION = "AUTHENTICATION_ERROR"
    AUTHORIZATION = "AUTHORIZATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT = "RATE_LIMIT_EXCEEDED"
    COMPLEXITY_LIMIT = "COMPLEXITY_LIMIT_EXCEEDED"
    DEPTH_LIMIT = "DEPTH_LIMIT_EXCEEDED"
    INTERNAL = "INTERNAL_ERROR"


# ============================================================================
# Main Error Processing
# ============================================================================


def process_graphql_errors(
    errors: list[GraphQLError],
    execution_context: ExecutionContext | None = None,
) -> list[GraphQLFormattedError]:
    """Process GraphQL errors before returning to client.

    This function:
    1. Logs all errors with full details server-side
    2. Masks internal errors in production
    3. Preserves user-facing errors (validation, auth, not found)
    4. Adds structured error codes to extensions

    Args:
        errors: List of GraphQL errors from execution
        execution_context: Execution context with operation info

    Returns:
        List of formatted errors safe to return to client
    """
    settings = get_settings()
    is_production = settings.environment == "production"

    processed_errors = []

    for error in errors:
        # Log full error details server-side
        log_error(error, execution_context)

        # Determine if this is a user-facing error
        if is_user_facing_error(error):
            # Keep the error as-is (validation, auth, etc.)
            processed_errors.append(error.formatted)
        else:
            # Mask internal errors in production
            if is_production:
                masked_error = mask_internal_error(error)
                processed_errors.append(masked_error)
            else:
                # In development, include full error details
                formatted = error.formatted
                # Add helpful debug info in development
                if error.original_error:
                    formatted["extensions"] = formatted.get("extensions", {})
                    formatted["extensions"]["debug"] = {
                        "exception_type": type(error.original_error).__name__,
                        "exception_message": str(error.original_error),
                    }
                processed_errors.append(formatted)

    return processed_errors


# ============================================================================
# Error Classification
# ============================================================================


def is_user_facing_error(error: GraphQLError) -> bool:
    """Determine if error should be shown to user as-is.

    User-facing errors are intentional errors that provide useful feedback:
    - Validation errors (invalid input)
    - Authentication errors (not logged in)
    - Authorization errors (insufficient permissions)
    - Not found errors (resource doesn't exist)
    - Rate limit errors
    - Query complexity/depth limit errors

    Args:
        error: GraphQL error to check

    Returns:
        True if error is safe to show to user, False if it should be masked
    """
    extensions = error.extensions or {}
    error_code = extensions.get("code", "")

    # Check for user-facing error codes
    user_facing_codes = [
        ErrorCategory.VALIDATION,
        ErrorCategory.AUTHENTICATION,
        ErrorCategory.AUTHORIZATION,
        ErrorCategory.NOT_FOUND,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.COMPLEXITY_LIMIT,
        ErrorCategory.DEPTH_LIMIT,
    ]

    if error_code in user_facing_codes:
        return True

    # Check error message patterns
    message_lower = error.message.lower()

    # Permission errors
    if any(
        pattern in message_lower
        for pattern in [
            "permission",
            "not authorized",
            "forbidden",
            "access denied",
        ]
    ):
        return True

    # Authentication errors
    if any(
        pattern in message_lower
        for pattern in [
            "not authenticated",
            "login required",
            "authentication required",
        ]
    ):
        return True

    # Validation errors
    if any(
        pattern in message_lower
        for pattern in [
            "invalid",
            "required",
            "must be",
            "cannot be",
            "too long",
            "too short",
        ]
    ):
        return True

    # Rate limit errors
    if "rate limit" in message_lower or "too many requests" in message_lower:
        return True

    # Not found errors
    # All other errors are internal and should be masked
    return "not found" in message_lower or "does not exist" in message_lower


# ============================================================================
# Error Masking
# ============================================================================


def mask_internal_error(error: GraphQLError) -> GraphQLFormattedError:
    """Mask internal error details for production.

    Replaces internal error details with a generic message while preserving
    the error location and path for debugging.

    Args:
        error: Original GraphQL error

    Returns:
        Formatted error safe for production
    """
    return {
        "message": "An internal error occurred. Please try again later.",
        "locations": error.locations,
        "path": error.path,
        "extensions": {
            "code": ErrorCategory.INTERNAL,
            "timestamp": _get_timestamp(),
        },
    }


# ============================================================================
# Error Logging
# ============================================================================


def log_error(error: GraphQLError, execution_context: ExecutionContext | None) -> None:
    """Log error with full details for server-side debugging.

    Args:
        error: GraphQL error to log
        execution_context: Execution context with operation info
    """
    # Build log context
    log_context = {
        "error_message": error.message,
        "error_path": error.path,
        "error_locations": error.locations,
    }

    # Add operation info if available
    if execution_context:
        if execution_context.operation_name:
            log_context["operation_name"] = execution_context.operation_name

        if hasattr(execution_context, "context") and execution_context.context:
            context = execution_context.context

            # Add user info if authenticated
            if hasattr(context, "user") and context.user:
                log_context["user_id"] = str(context.user.id)

            # Add correlation ID for tracing
            if hasattr(context, "correlation_id") and context.correlation_id:
                log_context["correlation_id"] = context.correlation_id

    # Add original exception details if available
    if error.original_error:
        log_context["exception_type"] = type(error.original_error).__name__
        log_context["exception_message"] = str(error.original_error)

        # Add stack trace for internal errors
        if not is_user_facing_error(error):
            log_context["stack_trace"] = "".join(
                traceback.format_exception(
                    type(error.original_error),
                    error.original_error,
                    error.original_error.__traceback__,
                )
            )

    # Log at appropriate level
    if is_user_facing_error(error):
        # User-facing errors are expected, log at INFO
        logger.info("GraphQL user-facing error", extra=log_context)
    else:
        # Internal errors are unexpected, log at ERROR
        logger.error("GraphQL internal error", extra=log_context)


# ============================================================================
# Validation Error Formatting
# ============================================================================


def format_validation_error(
    message: str,
    field: str | None = None,
    input_path: list[str | int] | None = None,
) -> GraphQLError:
    """Create a formatted validation error.

    Helper for creating consistent validation errors in resolvers.

    Args:
        message: Error message
        field: Field name that failed validation
        input_path: Path to the invalid input value

    Returns:
        GraphQL error with validation error extensions

    Example:
        if len(input.title) > 200:
            raise format_validation_error(
                message="Title must be at most 200 characters",
                field="title",
            )
    """
    extensions = {
        "code": ErrorCategory.VALIDATION,
    }

    if field:
        extensions["field"] = field

    if input_path:
        extensions["input_path"] = input_path

    return GraphQLError(
        message=message,
        extensions=extensions,
    )


def format_not_found_error(
    resource_type: str,
    resource_id: str | None = None,
) -> GraphQLError:
    """Create a formatted not found error.

    Args:
        resource_type: Type of resource (e.g., "Reminder", "User")
        resource_id: ID of the resource that wasn't found

    Returns:
        GraphQL error with not found extensions

    Example:
        reminder = await load_reminder(id)
        if not reminder:
            raise format_not_found_error("Reminder", id)
    """
    message = f"{resource_type} not found"
    if resource_id:
        message += f" (id: {resource_id})"

    return GraphQLError(
        message=message,
        extensions={
            "code": ErrorCategory.NOT_FOUND,
            "resource_type": resource_type,
            "resource_id": resource_id,
        },
    )


def format_permission_error(
    message: str | None = None,
    required_permission: str | None = None,
) -> GraphQLError:
    """Create a formatted permission error.

    Args:
        message: Custom error message
        required_permission: Permission that was required

    Returns:
        GraphQL error with authorization extensions

    Example:
        if not user.has_permission("reminders:delete"):
            raise format_permission_error(
                message="You don't have permission to delete reminders",
                required_permission="reminders:delete",
            )
    """
    if message is None:
        message = "You don't have permission to perform this action"

    extensions = {
        "code": ErrorCategory.AUTHORIZATION,
    }

    if required_permission:
        extensions["required_permission"] = required_permission

    return GraphQLError(
        message=message,
        extensions=extensions,
    )


# ============================================================================
# Helper Functions
# ============================================================================


def _get_timestamp() -> str:
    """Get current timestamp as ISO string.

    Returns:
        ISO 8601 timestamp
    """
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ============================================================================
# Custom Exception Classes (Optional)
# ============================================================================


class GraphQLValidationError(Exception):
    """Validation error for GraphQL inputs.

    Raise this in resolvers to create a properly formatted validation error.

    Example:
        if len(input.title) > 200:
            raise GraphQLValidationError("Title too long", field="title")
    """

    def __init__(self, message: str, field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(message)

    def to_graphql_error(self) -> GraphQLError:
        """Convert to GraphQL error."""
        return format_validation_error(self.message, self.field)


class GraphQLNotFoundError(Exception):
    """Not found error for GraphQL resources.

    Example:
        reminder = await load_reminder(id)
        if not reminder:
            raise GraphQLNotFoundError("Reminder", id)
    """

    def __init__(self, resource_type: str, resource_id: str | None = None):
        self.resource_type = resource_type
        self.resource_id = resource_id
        message = f"{resource_type} not found"
        if resource_id:
            message += f" (id: {resource_id})"
        super().__init__(message)

    def to_graphql_error(self) -> GraphQLError:
        """Convert to GraphQL error."""
        return format_not_found_error(self.resource_type, self.resource_id)


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Using error handler in schema
    from example_service.features.graphql.error_handler import process_graphql_errors

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        subscription=Subscription,
        process_errors=process_graphql_errors,
    )

Example: Raising validation errors in resolvers
    @strawberry.mutation
    async def create_reminder(
        self,
        info: Info,
        input: CreateReminderInput,
    ) -> ReminderPayload:
        # Option 1: Return error in union type (preferred)
        if len(input.title) > 200:
            return ReminderError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Title must be at most 200 characters",
                field="title",
            )

        # Option 2: Raise GraphQL error
        if not input.title.strip():
            raise format_validation_error(
                message="Title cannot be empty",
                field="title",
            )

        # Option 3: Raise custom exception
        if len(input.description or "") > 5000:
            raise GraphQLValidationError("Description too long", field="description")

Example: Handling not found errors
    @strawberry.field
    async def reminder(self, info: Info, id: strawberry.ID) -> ReminderType | None:
        reminder = await load_reminder(id)

        # Option 1: Return None (query returns nullable)
        if not reminder:
            return None

        # Option 2: Raise error if null is not acceptable
        if not reminder:
            raise format_not_found_error("Reminder", str(id))

        return ReminderType.from_pydantic(...)

Example: Production vs Development behavior
    # In production (environment=production):
    # - Internal errors masked: "An internal error occurred"
    # - Full error logged server-side with stack trace
    # - Client sees generic message + error code

    # In development:
    # - Full error details returned to client
    # - Debug info included in extensions
    # - Stack traces visible

Example: Error logging structure
    {
        "error_message": "Database connection failed",
        "error_path": ["createReminder"],
        "operation_name": "CreateReminder",
        "user_id": "123e4567-e89b-12d3-a456-426614174000",
        "correlation_id": "req_abc123",
        "exception_type": "OperationalError",
        "stack_trace": "Traceback (most recent call last)..."
    }
"""
