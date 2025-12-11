"""Exception types and statistics helpers for retry utilities."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetryStatistics:
    """Statistics captured during a retry session."""

    attempts: int = 0
    total_delay: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    exceptions: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Total time spent retrying."""
        return self.end_time - self.start_time


class RetryError(Exception):
    """Error raised after exhausting retry attempts."""

    def __init__(
        self,
        last_exception: Exception,
        attempts: int,
        statistics: RetryStatistics | None = None,
    ) -> None:
        """Initialize the error with context."""
        self.last_exception = last_exception
        self.attempts = attempts
        self.statistics = statistics
        super().__init__(f"Failed after {attempts} attempts. Last error: {last_exception}")
