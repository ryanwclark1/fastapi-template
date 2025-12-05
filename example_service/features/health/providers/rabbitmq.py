"""RabbitMQ health check provider.

Monitors RabbitMQ messaging broker health and connection state.
"""

from __future__ import annotations

import logging
import time

from example_service.core.schemas.common import HealthStatus

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


class RabbitMQHealthProvider:
    """Health provider for RabbitMQ messaging broker.

    Uses the check_broker_health() function from infra.messaging.broker
    to check broker connection state and health status.

    Example:
        >>> from example_service.infra.messaging.broker import check_broker_health
        >>> rabbit_provider = RabbitMQHealthProvider()
        >>> aggregator.add_provider(rabbit_provider)
    """

    def __init__(self, timeout: float = 5.0) -> None:
        """Initialize RabbitMQ health provider.

        Args:
            timeout: Health check timeout in seconds
        """
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Return provider name."""
        return "messaging"

    async def check_health(self) -> HealthCheckResult:
        """Check RabbitMQ broker health using check_broker_health().

        Uses the centralized health check function from infra.messaging.broker
        which provides connection state and detailed health information.
        """
        from example_service.infra.messaging.broker import check_broker_health

        start_time = time.perf_counter()

        try:
            health_info = await check_broker_health()
            latency_ms = (time.perf_counter() - start_time) * 1000

            status_str = health_info.get("status", "unknown")
            state = health_info.get("state", "unknown")
            is_connected = health_info.get("is_connected", False)
            reason = health_info.get("reason")

            # Map status to HealthStatus enum
            if status_str == "healthy" and is_connected:
                health_status = HealthStatus.HEALTHY
                message = f"Messaging broker operational (state: {state})"
            elif status_str == "unavailable":
                health_status = HealthStatus.UNHEALTHY
                message = f"Messaging broker unavailable: {reason or 'not configured'}"
            else:
                health_status = HealthStatus.UNHEALTHY
                message = f"Messaging broker unhealthy: {reason or 'unknown error'}"

            return HealthCheckResult(
                status=health_status,
                message=message,
                latency_ms=latency_ms,
                metadata={
                    "connection_state": state,
                    "is_connected": is_connected,
                    "reason": reason,
                },
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("RabbitMQ health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Broker health check error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )
