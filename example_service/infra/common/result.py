"""Unified result type for infrastructure operations.

Provides a consistent way to represent success/failure across
different infrastructure components (AI, Email, Storage, etc.).

Usage:
    # Success case
    result = InfraResult.ok(data=transcription, metadata={"model": "whisper"})

    # Failure case
    result = InfraResult.fail(error="Connection timeout", code="TIMEOUT")

    # Check result
    if result.success:
        process(result.data)
    else:
        handle_error(result.error, result.error_code)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class InfraResult[T]:
    """Result of an infrastructure operation.

    A unified result type that can represent either success or failure
    for operations across AI, Email, Storage, and other infrastructure.

    Attributes:
        success: Whether the operation succeeded
        data: The result data (None on failure)
        error: Error message (None on success)
        error_code: Machine-readable error code (None on success)
        metadata: Additional metadata about the operation
        duration_ms: Operation duration in milliseconds (optional)
        timestamp: When the operation completed

    Example:
        # Creating results
        result = InfraResult.ok(data={"transcript": "..."})
        result = InfraResult.fail(error="API rate limited", code="RATE_LIMITED")

        # Using results
        if result.success:
            transcript = result.data["transcript"]
        else:
            logger.error(f"Failed: {result.error} ({result.error_code})")

        # With metadata
        result = InfraResult.ok(
            data=email_id,
            metadata={"provider": "sendgrid", "message_id": "abc123"},
            duration_ms=150,
        )
    """

    success: bool
    data: T | None = None
    error: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def ok(
        cls,
        data: T,
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> InfraResult[T]:
        """Create a successful result.

        Args:
            data: The result data
            metadata: Optional metadata dict
            duration_ms: Optional duration in milliseconds

        Returns:
            InfraResult with success=True
        """
        return cls(
            success=True,
            data=data,
            metadata=metadata or {},
            duration_ms=duration_ms,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        code: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> InfraResult[T]:
        """Create a failure result.

        Args:
            error: Human-readable error message
            code: Machine-readable error code (e.g., "TIMEOUT", "AUTH_FAILED")
            metadata: Optional metadata dict
            duration_ms: Optional duration in milliseconds

        Returns:
            InfraResult with success=False
        """
        return cls(
            success=False,
            error=error,
            error_code=code,
            metadata=metadata or {},
            duration_ms=duration_ms,
        )

    def map(self, func: Any) -> InfraResult[Any]:
        """Transform the data if successful.

        Args:
            func: Function to apply to data

        Returns:
            New InfraResult with transformed data, or same failure
        """
        if self.success and self.data is not None:
            return InfraResult.ok(
                data=func(self.data),
                metadata=self.metadata,
                duration_ms=self.duration_ms,
            )
        return InfraResult.fail(
            error=self.error or "Unknown error",
            code=self.error_code,
            metadata=self.metadata,
            duration_ms=self.duration_ms,
        )

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success
