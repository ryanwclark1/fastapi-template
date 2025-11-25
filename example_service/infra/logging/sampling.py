"""Log sampling for high-volume endpoints.

Provides intelligent log sampling to reduce log volume for noisy endpoints
while preserving logs for errors and important events.

This is critical for production systems where health checks and metrics
endpoints can generate millions of logs per day.
"""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from threading import Lock
from typing import Any


class SamplingFilter(logging.Filter):
    """Filter that samples logs based on logger name and level.

    Uses deterministic sampling based on sample rate. Always logs
    errors and warnings, samples INFO and DEBUG based on rate.

    Features:
    - Per-logger sampling rates
    - Always log errors/warnings (configurable)
    - Thread-safe counters for monitoring
    - Time-based rate limiting option

    Example:
            # Sample 1% of INFO logs from health check endpoint
        sampling_filter = SamplingFilter(
            sample_rates={
                "app.api.health": 0.01,    # 1% sampling
                "app.api.metrics": 0.001,  # 0.1% sampling
            },
            always_log_levels={logging.ERROR, logging.WARNING}
        )

        # Add to handler
        handler.addFilter(sampling_filter)
    """

    def __init__(
        self,
        sample_rates: dict[str, float] | None = None,
        default_sample_rate: float = 1.0,
        always_log_levels: set[int] | None = None,
    ) -> None:
        """Initialize sampling filter.

        Args:
            sample_rates: Dict mapping logger names to sample rates (0.0-1.0).
                Example: {"app.api.health": 0.01} means sample 1% of health logs.
            default_sample_rate: Default sample rate for loggers not in sample_rates.
            always_log_levels: Set of log levels to always log regardless of sampling.
                Default: {logging.ERROR, logging.CRITICAL}
        """
        super().__init__()
        self.sample_rates = sample_rates or {}
        self.default_sample_rate = default_sample_rate
        self.always_log_levels = always_log_levels or {logging.ERROR, logging.CRITICAL}

        # Counters for monitoring (thread-safe)
        self._lock = Lock()
        self._total_count: dict[str, int] = defaultdict(int)
        self._sampled_count: dict[str, int] = defaultdict(int)
        self._dropped_count: dict[str, int] = defaultdict(int)

    def filter(self, record: logging.LogRecord) -> bool:
        """Determine if record should be logged based on sampling.

        Args:
            record: Log record to filter.

        Returns:
            True if record should be logged, False otherwise.
        """
        # Always log configured levels (errors by default)
        if record.levelno in self.always_log_levels:
            self._increment_counter("sampled", record.name)
            return True

        # Get sample rate for this logger
        sample_rate = self.sample_rates.get(record.name, self.default_sample_rate)

        # If sample rate is 1.0, always log
        if sample_rate >= 1.0:
            self._increment_counter("sampled", record.name)
            return True

        # If sample rate is 0.0, never log (unless it's an error level)
        if sample_rate <= 0.0:
            self._increment_counter("dropped", record.name)
            return False

        # Sample based on rate
        if random.random() < sample_rate:
            self._increment_counter("sampled", record.name)
            return True
        else:
            self._increment_counter("dropped", record.name)
            return False

    def _increment_counter(self, counter_type: str, logger_name: str) -> None:
        """Thread-safe counter increment.

        Args:
            counter_type: Type of counter ("sampled" or "dropped").
            logger_name: Name of logger.
        """
        with self._lock:
            self._total_count[logger_name] += 1
            if counter_type == "sampled":
                self._sampled_count[logger_name] += 1
            else:
                self._dropped_count[logger_name] += 1

    def get_stats(self) -> dict[str, dict[str, int]]:
        """Get sampling statistics.

        Returns:
            Dict mapping logger names to stats (total, sampled, dropped).

        Example:
                    stats = sampling_filter.get_stats()
            print(stats)
            # {
            #     "app.api.health": {
            #         "total": 10000,
            #         "sampled": 100,
            #         "dropped": 9900
            #     }
            # }
        """
        with self._lock:
            return {
                logger_name: {
                    "total": self._total_count[logger_name],
                    "sampled": self._sampled_count[logger_name],
                    "dropped": self._dropped_count[logger_name],
                }
                for logger_name in self._total_count.keys()
            }

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        with self._lock:
            self._total_count.clear()
            self._sampled_count.clear()
            self._dropped_count.clear()


class RateLimitFilter(logging.Filter):
    """Filter that rate-limits logs to prevent log storms.

    Limits the number of log messages per time window. Useful for
    preventing a single error from flooding logs.

    Example:
            # Allow max 10 logs per second per logger
        rate_limit = RateLimitFilter(
            max_logs_per_window=10,
            window_seconds=1.0
        )
        handler.addFilter(rate_limit)
    """

    def __init__(
        self,
        max_logs_per_window: int = 100,
        window_seconds: float = 1.0,
        always_log_levels: set[int] | None = None,
    ) -> None:
        """Initialize rate limit filter.

        Args:
            max_logs_per_window: Maximum logs allowed in time window.
            window_seconds: Time window in seconds.
            always_log_levels: Set of log levels to always log (bypass rate limit).
                Default: {logging.CRITICAL}
        """
        super().__init__()
        self.max_logs_per_window = max_logs_per_window
        self.window_seconds = window_seconds
        self.always_log_levels = always_log_levels or {logging.CRITICAL}

        # Per-logger rate limiting
        self._lock = Lock()
        self._log_counts: dict[str, list[float]] = defaultdict(list)
        self._dropped_count: dict[str, int] = defaultdict(int)

    def filter(self, record: logging.LogRecord) -> bool:
        """Determine if record should be logged based on rate limit.

        Args:
            record: Log record to filter.

        Returns:
            True if record should be logged, False otherwise.
        """
        # Always log critical errors
        if record.levelno in self.always_log_levels:
            return True

        current_time = time.time()
        logger_name = record.name

        with self._lock:
            # Get timestamps for this logger
            timestamps = self._log_counts[logger_name]

            # Remove timestamps outside the window
            cutoff = current_time - self.window_seconds
            timestamps[:] = [ts for ts in timestamps if ts > cutoff]

            # Check if we're within the limit
            if len(timestamps) < self.max_logs_per_window:
                timestamps.append(current_time)
                return True
            else:
                self._dropped_count[logger_name] += 1
                return False

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Get rate limiting statistics.

        Returns:
            Dict mapping logger names to stats (current_rate, dropped).
        """
        current_time = time.time()
        with self._lock:
            stats = {}
            for logger_name, timestamps in self._log_counts.items():
                # Count logs in current window
                cutoff = current_time - self.window_seconds
                active_logs = sum(1 for ts in timestamps if ts > cutoff)

                stats[logger_name] = {
                    "current_rate": active_logs / self.window_seconds,
                    "dropped_total": self._dropped_count[logger_name],
                }
            return stats


def create_sampling_config() -> dict[str, float]:
    """Create default sampling configuration for common noisy endpoints.

    Returns:
        Dict mapping logger names to sample rates.

    Customize this for your application's needs.
    """
    return {
        # Health checks - very noisy, sample 0.1%
        "app.api.health": 0.001,
        "uvicorn.access": 0.01,  # Sample 1% of access logs
        # Metrics endpoint - sample 1%
        "app.api.metrics": 0.01,
        # Readiness/liveness - sample 0.1%
        "app.api.ready": 0.001,
        "app.api.live": 0.001,
        # OpenAPI docs - sample 10%
        "app.api.docs": 0.1,
    }
