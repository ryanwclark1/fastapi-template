"""Database repository exceptions.

Custom exceptions for repository operations that provide better
error messages and typing than raw SQLAlchemy exceptions.
"""
from __future__ import annotations

from typing import Any


class RepositoryError(Exception):
    """Base exception for repository operations.

    Raised when a repository operation fails due to programming
    errors, configuration issues, or unexpected states.

    This is distinct from data-related errors (NotFoundError) and
    indicates a problem with the repository itself.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """Initialize repository error.

        Args:
            message: Error description
            details: Additional context about the error
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Format error message with details."""
        if self.details:
            details_str = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class NotFoundError(RepositoryError):
    """Entity not found in database.

    Raised when querying for an entity by primary key or unique
    field that doesn't exist.

    This is a data-level error (404-like) rather than a system error.

    Attributes:
        model_name: Name of the model class that wasn't found
        identifier: The key/value that was searched for
    """

    def __init__(self, model_name: str, identifier: dict[str, Any]):
        """Initialize not found error.

        Args:
            model_name: Name of the model (e.g., "User", "Post")
            identifier: Key-value pairs used in the search (e.g., {"id": 123})
        """
        self.model_name = model_name
        self.identifier = identifier

        # Build friendly error message
        id_str = ", ".join(f"{k}={v!r}" for k, v in identifier.items())
        message = f"{model_name} not found with {id_str}"

        super().__init__(message, details={"model": model_name, **identifier})

    def __repr__(self) -> str:
        """Repr for debugging."""
        return f"NotFoundError(model={self.model_name!r}, identifier={self.identifier!r})"


class MultipleResultsFoundError(RepositoryError):
    """Multiple entities found when expecting one.

    Raised when a query expected to return a single result (e.g.,
    unique field lookup) returns multiple rows.

    This usually indicates:
    - Missing or incorrect unique constraints
    - Corrupted data
    - Query logic error
    """

    def __init__(self, model_name: str, filter_description: str):
        """Initialize multiple results error.

        Args:
            model_name: Name of the model
            filter_description: Description of the filter that matched multiple rows
        """
        self.model_name = model_name
        self.filter_description = filter_description

        message = (
            f"Expected one {model_name}, found multiple matching: {filter_description}"
        )
        super().__init__(
            message, details={"model": model_name, "filter": filter_description}
        )


class InvalidFilterError(RepositoryError):
    """Invalid filter or query parameters.

    Raised when filter parameters are malformed, reference non-existent
    fields, or contain invalid values.
    """

    def __init__(self, message: str, filter_name: str | None = None):
        """Initialize invalid filter error.

        Args:
            message: Error description
            filter_name: Name of the problematic filter (if applicable)
        """
        details = {"filter": filter_name} if filter_name else {}
        super().__init__(message, details=details)


__all__ = [
    "RepositoryError",
    "NotFoundError",
    "MultipleResultsFoundError",
    "InvalidFilterError",
]
