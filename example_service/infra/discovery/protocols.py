"""Protocol definitions for Consul client abstraction.

This module defines the ConsulClientProtocol that allows for:
- Easy testing with mock implementations
- Dependency injection of different client implementations
- Clear contract for what operations are supported
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConsulClientProtocol(Protocol):
    """Protocol for Consul client operations.

    This protocol defines the contract for Consul service registration
    and health check operations. It enables:
    - Unit testing with MockConsulClient
    - Dependency injection in ConsulService
    - Future alternative implementations (e.g., different HTTP clients)

    All methods are async and should handle errors gracefully,
    returning success/failure status rather than raising exceptions.
    """

    async def register_service(
        self,
        service_id: str,
        service_name: str,
        address: str,
        port: int,
        tags: list[str],
        meta: dict[str, str],
        check: dict[str, Any],
    ) -> bool:
        """Register a service with Consul agent.

        Args:
            service_id: Unique identifier for this service instance.
            service_name: Logical name of the service.
            address: IP address or hostname to advertise.
            port: Port number to advertise.
            tags: List of tags for filtering and routing.
            meta: Key-value metadata for the service.
            check: Health check definition (TTL or HTTP).

        Returns:
            True if registration succeeded, False otherwise.
        """
        ...

    async def deregister_service(self, service_id: str) -> bool:
        """Deregister a service from Consul agent.

        Args:
            service_id: The service instance ID to deregister.

        Returns:
            True if deregistration succeeded, False otherwise.
        """
        ...

    async def pass_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check pass to mark service as healthy.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL pass succeeded, False otherwise.
        """
        ...

    async def fail_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check fail to mark service as unhealthy.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL fail succeeded, False otherwise.
        """
        ...

    async def warn_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check warn to mark service as degraded.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL warn succeeded, False otherwise.
        """
        ...

    async def close(self) -> None:
        """Close the client and release resources.

        This should be called during shutdown to properly clean up
        HTTP connections and other resources.
        """
        ...
