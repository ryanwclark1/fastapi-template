"""Database connection pool health check provider.

Monitors SQLAlchemy connection pool utilization and alerts when pool is
nearing exhaustion.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings.health import ProviderConfig

from .protocol import HealthCheckResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class DatabasePoolHealthProvider:
    """Health provider for database connection pool monitoring.

    Monitors SQLAlchemy connection pool utilization and alerts when
    pool is nearing exhaustion. Critical for preventing connection
    pool errors under load.

    Status Levels:
    - HEALTHY: Pool utilization < 70% (default degraded threshold)
    - DEGRADED: Pool utilization 70-90% (default unhealthy threshold)
    - UNHEALTHY: Pool utilization > 90%

    For test environments using NullPool, always returns HEALTHY with
    a note in metadata.

    Example:
        >>> from example_service.infra.database.session import engine
        >>> provider = DatabasePoolHealthProvider(
        ...     engine=engine,
        ...     degraded_threshold=0.7,
        ...     unhealthy_threshold=0.9
        ... )
        >>> aggregator.add_provider(provider)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        degraded_threshold: float = 0.7,
        unhealthy_threshold: float = 0.9,
        config: ProviderConfig | None = None,
    ) -> None:
        """Initialize database pool health provider.

        Args:
            engine: SQLAlchemy async engine instance
            degraded_threshold: Pool utilization threshold for DEGRADED status (0.0-1.0)
            unhealthy_threshold: Pool utilization threshold for UNHEALTHY status (0.0-1.0)
            config: Optional configuration (primarily for consistency with other providers)

        Raises:
            ValueError: If thresholds are invalid or degraded >= unhealthy
        """
        if not (0.0 <= degraded_threshold <= 1.0):
            msg = f"degraded_threshold must be between 0.0 and 1.0, got {degraded_threshold}"
            raise ValueError(
                msg,
            )

        if not (0.0 <= unhealthy_threshold <= 1.0):
            msg = f"unhealthy_threshold must be between 0.0 and 1.0, got {unhealthy_threshold}"
            raise ValueError(
                msg,
            )

        if degraded_threshold >= unhealthy_threshold:
            msg = (
                f"degraded_threshold ({degraded_threshold}) must be less than "
                f"unhealthy_threshold ({unhealthy_threshold})"
            )
            raise ValueError(
                msg,
            )

        self._engine = engine
        self._degraded_threshold = degraded_threshold
        self._unhealthy_threshold = unhealthy_threshold
        self._config = config or ProviderConfig()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "database_pool"

    async def check_health(self) -> HealthCheckResult:
        """Check connection pool health.

        Examines the connection pool to determine utilization and
        returns status based on configured thresholds. This is a
        fast, non-blocking check that only reads pool statistics.

        Returns:
            HealthCheckResult with pool metrics in metadata including:
            - pool_size: Total configured pool size
            - checked_out: Connections currently in use
            - checked_in: Idle connections available
            - overflow: Overflow connections (beyond pool_size)
            - utilization_percent: Percentage of pool in use
            - available: Connections available for checkout
            - pool_class: Pool class name (QueuePool, NullPool, etc.)
        """
        start_time = time.perf_counter()

        try:
            # Access the underlying pool
            pool = self._engine.pool

            # Get pool class name
            pool_class = type(pool).__name__

            # Handle NullPool (test environments)
            if pool_class == "NullPool":
                latency_ms = (time.perf_counter() - start_time) * 1000
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message="NullPool in use (test environment)",
                    latency_ms=latency_ms,
                    metadata={
                        "pool_class": pool_class,
                        "note": "NullPool creates connections on-demand without pooling",
                    },
                )

            # Collect pool statistics
            # QueuePool and related pool types have these methods
            # Type ignore needed because mypy doesn't know about these dynamic attributes
            pool_size = pool.size()  # type: ignore[attr-defined]  # Total pool size
            checked_out = pool.checkedout()  # type: ignore[attr-defined]  # Connections in use
            overflow = pool.overflow()  # type: ignore[attr-defined]  # Overflow connections beyond pool_size
            checked_in = pool.checkedin()  # type: ignore[attr-defined]  # Idle connections

            # Calculate utilization
            total_capacity = pool_size + overflow
            utilization = 0.0 if total_capacity == 0 else checked_out / total_capacity

            utilization_percent = utilization * 100
            available = checked_in

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Build metadata
            metadata = {
                "pool_size": pool_size,
                "checked_out": checked_out,
                "checked_in": checked_in,
                "overflow": overflow,
                "utilization_percent": round(utilization_percent, 2),
                "available": available,
                "pool_class": pool_class,
            }

            # Determine status based on utilization
            if utilization >= self._unhealthy_threshold:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Pool critically high: {utilization_percent:.1f}% utilized",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            if utilization >= self._degraded_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Pool utilization elevated: {utilization_percent:.1f}%",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"Pool healthy: {utilization_percent:.1f}% utilized",
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except AttributeError as e:
            # Pool doesn't have expected methods (unexpected pool type)
            latency_ms = (time.perf_counter() - start_time) * 1000
            pool_class = type(pool).__name__ if hasattr(self._engine, "pool") else "unknown"
            logger.warning(
                "Pool health check failed - unsupported pool type",
                extra={"pool_class": pool_class, "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"Unsupported pool type: {pool_class}",
                latency_ms=latency_ms,
                metadata={
                    "pool_class": pool_class,
                    "note": "Pool statistics not available for this pool type",
                },
            )

        except Exception as e:
            # Unexpected error accessing pool
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("Unexpected error in pool health check", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Pool check error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e), "error_type": type(e).__name__},
            )
