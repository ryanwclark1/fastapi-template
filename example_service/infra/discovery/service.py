"""Consul service discovery orchestrator.

This module provides the high-level ConsulService that manages:
- Service registration with Consul
- TTL heartbeat background task
- Health-aware status updates
- Graceful startup and shutdown

The service is designed to NEVER block application startup:
- All errors are logged but not raised
- start() returns bool to indicate success
- The application runs normally even if Consul is unavailable
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from example_service.core.settings.consul import ConsulSettings, HealthCheckMode
from example_service.infra.discovery.address import resolve_advertise_address
from example_service.infra.discovery.client import ConsulClient

if TYPE_CHECKING:
    from example_service.core.services.health import HealthService
    from example_service.infra.discovery.protocols import ConsulClientProtocol

logger = logging.getLogger(__name__)


class ConsulService:
    """High-level service discovery manager.

    This class orchestrates Consul service registration and manages
    the TTL heartbeat loop. It integrates with the application's
    HealthService to report accurate health status to Consul.

    Key behaviors:
    - Never blocks application startup
    - Gracefully handles Consul unavailability
    - Background heartbeat task for TTL mode
    - Health-aware status reporting

    Example:
        service = ConsulService(settings=get_consul_settings())
        success = await service.start()  # Returns False on failure, never raises

        # ... application runs ...

        await service.stop()  # Deregisters and cleans up
    """

    def __init__(
        self,
        settings: ConsulSettings | None = None,
        client: ConsulClientProtocol | None = None,
        health_service: HealthService | None = None,
        service_name: str | None = None,
    ) -> None:
        """Initialize the Consul service.

        Args:
            settings: ConsulSettings instance. If None, loads from environment.
            client: Consul client implementation. If None, creates ConsulClient.
                    Pass MockConsulClient for testing.
            health_service: Application health service for status reporting.
                           If None, always reports healthy.
            service_name: Service name override. If None, uses settings or app settings.
        """
        from example_service.core.settings import get_app_settings, get_consul_settings

        self._settings = settings or get_consul_settings()
        self._app_settings = get_app_settings()
        self._health_service = health_service

        # Determine service name
        self._service_name = (
            service_name
            or self._settings.service_name
            or self._app_settings.service_name
        )

        # Generate unique service ID
        self._service_id = f"{self._service_name}-{uuid4()}"
        self._check_id = f"service:{self._service_id}"

        # Client - created lazily or injected
        self._client: ConsulClientProtocol | None = client
        self._owns_client = client is None  # Track if we created the client

        # State
        self._registered = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        logger.debug(
            "ConsulService initialized",
            extra={
                "service_name": self._service_name,
                "service_id": self._service_id,
                "health_check_mode": self._settings.health_check_mode.value,
            },
        )

    @property
    def is_registered(self) -> bool:
        """Check if the service is currently registered with Consul."""
        return self._registered

    @property
    def service_id(self) -> str:
        """Get the unique service instance ID."""
        return self._service_id

    async def start(self) -> bool:
        """Start service discovery registration.

        This method:
        1. Resolves the advertise address
        2. Registers the service with Consul
        3. Starts the heartbeat task (TTL mode only)

        Returns:
            True if registration succeeded, False otherwise.
            NEVER raises exceptions - failures are logged.

        Example:
            success = await service.start()
            if not success:
                logger.warning("Running without service discovery")
        """
        if not self._settings.is_configured:
            logger.debug("Consul service discovery not configured, skipping")
            return False

        try:
            # Create client if not injected
            if self._client is None:
                self._client = ConsulClient(self._settings)

            # Resolve advertise address
            address = resolve_advertise_address(
                configured_address=self._settings.service_address,
                interface_hint=self._settings.service_address_interface,
            )
            port = self._settings.service_port

            # Build health check definition
            if self._settings.health_check_mode == HealthCheckMode.TTL:
                check = self._settings.build_ttl_check_definition()
            else:
                check = self._settings.build_http_check_definition(address, port)

            # Build tags (include service ID for uniqueness)
            tags = [self._service_id, self._service_name, *self._settings.tags]

            # Register with Consul
            success = await self._client.register_service(
                service_id=self._service_id,
                service_name=self._service_name,
                address=address,
                port=port,
                tags=tags,
                meta=dict(self._settings.meta),
                check=check,
            )

            if not success:
                logger.warning(
                    "Failed to register with Consul, continuing without service discovery",
                    extra={"service_id": self._service_id},
                )
                return False

            self._registered = True

            # Start heartbeat task for TTL mode
            if self._settings.health_check_mode == HealthCheckMode.TTL:
                self._stop_event.clear()
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(),
                    name=f"consul-heartbeat-{self._service_id}",
                )

            logger.info(
                "Consul service discovery started",
                extra={
                    "service_id": self._service_id,
                    "service_name": self._service_name,
                    "address": address,
                    "port": port,
                    "health_check_mode": self._settings.health_check_mode.value,
                },
            )
            return True

        except Exception as e:
            logger.warning(
                "Error starting Consul service discovery, continuing without it",
                extra={"service_id": self._service_id, "error": str(e)},
            )
            return False

    async def stop(self) -> None:
        """Stop service discovery and deregister.

        This method:
        1. Cancels the heartbeat task
        2. Deregisters from Consul
        3. Closes the client

        This method NEVER raises exceptions - all errors are logged.
        """
        # Stop heartbeat task
        if self._heartbeat_task is not None:
            self._stop_event.set()
            try:
                # Wait for task to finish with timeout
                await asyncio.wait_for(self._heartbeat_task, timeout=5.0)
            except TimeoutError:
                logger.warning("Heartbeat task did not stop in time, cancelling")
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            except Exception as e:
                logger.warning("Error stopping heartbeat task", extra={"error": str(e)})
            finally:
                self._heartbeat_task = None

        # Deregister from Consul
        if self._registered and self._client is not None:
            try:
                success = await self._client.deregister_service(self._service_id)
                if success:
                    logger.info(
                        "Service deregistered from Consul",
                        extra={"service_id": self._service_id},
                    )
                else:
                    logger.warning(
                        "Failed to deregister from Consul",
                        extra={"service_id": self._service_id},
                    )
            except Exception as e:
                logger.warning(
                    "Error deregistering from Consul",
                    extra={"service_id": self._service_id, "error": str(e)},
                )
            finally:
                self._registered = False

        # Close client if we created it
        if self._owns_client and self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Error closing Consul client", extra={"error": str(e)})
            finally:
                self._client = None

        logger.debug(
            "ConsulService stopped",
            extra={"service_id": self._service_id},
        )

    async def _heartbeat_loop(self) -> None:
        """Background task that sends TTL heartbeats to Consul.

        This loop:
        1. Checks application health (if health_service is available)
        2. Sends pass/warn/fail to Consul based on health status
        3. Sleeps for the configured heartbeat interval
        4. Repeats until stop() is called
        """
        interval = self._settings.ttl_heartbeat_interval

        while not self._stop_event.is_set():
            try:
                # Check application health
                health_status = await self._check_app_health()

                # Send appropriate TTL update
                if self._client is not None:
                    if health_status == "healthy":
                        await self._client.pass_ttl(self._check_id)
                    elif health_status == "degraded":
                        await self._client.warn_ttl(self._check_id, note="App health degraded")
                    else:
                        await self._client.fail_ttl(self._check_id, note="App health check failed")

            except Exception as e:
                logger.warning(
                    "Error in heartbeat loop",
                    extra={"service_id": self._service_id, "error": str(e)},
                )

            # Wait for next interval or stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval,
                )
                # If we get here, stop was signaled
                break
            except TimeoutError:
                # Normal case - continue loop
                continue

    async def _check_app_health(self) -> str:
        """Check application health status.

        Returns:
            "healthy", "degraded", or "unhealthy"
        """
        if self._health_service is None:
            # No health service - assume healthy
            return "healthy"

        try:
            # Use the health service to check overall health
            result = await self._health_service.check_health()

            # Map health status to Consul TTL states
            status = result.get("status", "unknown")
            if status == "healthy":
                return "healthy"
            elif status == "degraded":
                return "degraded"
            else:
                return "unhealthy"

        except Exception as e:
            logger.warning("Error checking app health", extra={"error": str(e)})
            return "unhealthy"


# ──────────────────────────────────────────────────────────────
# Module-level state and lifecycle functions
# ──────────────────────────────────────────────────────────────

_service: ConsulService | None = None


async def start_discovery(
    health_service: HealthService | None = None,
) -> bool:
    """Start Consul service discovery.

    This is the main entry point for starting service discovery.
    Call this during application startup.

    Args:
        health_service: Optional health service for status reporting.

    Returns:
        True if registration succeeded, False otherwise.
        NEVER raises exceptions.

    Example:
        # In lifespan.py
        from example_service.infra.discovery import start_discovery

        success = await start_discovery()
        if success:
            logger.info("Service discovery started")
    """
    global _service

    from example_service.core.settings import get_consul_settings

    settings = get_consul_settings()

    if not settings.is_configured:
        logger.debug("Consul service discovery not configured")
        return False

    _service = ConsulService(
        settings=settings,
        health_service=health_service,
    )

    return await _service.start()


async def stop_discovery() -> None:
    """Stop Consul service discovery.

    Call this during application shutdown.
    This method NEVER raises exceptions.

    Example:
        # In lifespan.py
        from example_service.infra.discovery import stop_discovery

        await stop_discovery()
    """
    global _service

    if _service is not None:
        await _service.stop()
        _service = None


def get_discovery_service() -> ConsulService | None:
    """Get the current service discovery instance.

    Returns:
        ConsulService instance if started, None otherwise.
    """
    return _service
