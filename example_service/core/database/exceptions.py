"""Database operation exceptions.

Custom exceptions for database operations that provide better
error messages and typing than raw SQLAlchemy exceptions.
"""
from __future__ import annotations

from typing import Any


class DatabaseError(Exception):
    """Base exception for database operations.

    Raised when a database operation fails due to programming
    errors, configuration issues, or unexpected states.

    This is distinct from data-related errors (NotFoundError) and
    indicates a problem with the database operation itself.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """Initialize database error.

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


class NotFoundError(DatabaseError):
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


__all__ = [
    "DatabaseError",
    "NotFoundError",
]
