"""Database health check provider.

Executes a simple query to verify PostgreSQL database connectivity and
measures response latency. Marks as DEGRADED if latency exceeds threshold.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus

from .protocol import DEGRADED_LATENCY_THRESHOLD_MS, HealthCheckResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class DatabaseHealthProvider:
    """Health provider for PostgreSQL database connectivity.

    Executes a simple query to verify database connectivity and measures
    response latency. Marks as DEGRADED if latency exceeds threshold.

    Example:
        >>> from example_service.infra.database.session import engine
        >>> db_provider = DatabaseHealthProvider(engine, timeout=2.0)
        >>> aggregator.add_provider(db_provider)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        timeout: float = 2.0,
        latency_threshold_ms: float = DEGRADED_LATENCY_THRESHOLD_MS,
    ) -> None:
        """Initialize database health provider.

        Args:
            engine: SQLAlchemy async engine instance
            timeout: Health check timeout in seconds
            latency_threshold_ms: Latency threshold for DEGRADED status
        """
        self._engine = engine
        self._timeout = timeout
        self._latency_threshold = latency_threshold_ms

    @property
    def name(self) -> str:
        """Return provider name."""
        return "database"

    async def check_health(self) -> HealthCheckResult:
        """Check database connectivity with timeout."""
        import asyncio

        from sqlalchemy import text

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._timeout):
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            latency_ms = (time.perf_counter() - start_time) * 1000

            if latency_ms > self._latency_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Database operational",
                latency_ms=latency_ms,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Database health check timed out", extra={"timeout": self._timeout})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Database health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )
