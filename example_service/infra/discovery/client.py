"""Consul HTTP API client with observability.

This module provides a real Consul client implementation that:
- Uses httpx for async HTTP operations
- Includes OpenTelemetry tracing for all API calls
- Records Prometheus metrics for monitoring
- Handles errors gracefully without raising exceptions
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx
from opentelemetry import trace

from example_service.infra.discovery.metrics import (
    service_discovery_deregistrations_total,
    service_discovery_errors_total,
    service_discovery_operation_duration_seconds,
    service_discovery_registrations_total,
    service_discovery_ttl_passes_total,
)

if TYPE_CHECKING:
    from example_service.core.settings.consul import ConsulSettings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ConsulClient:
    """HTTP client for Consul Agent API with observability.

    This client implements ConsulClientProtocol and provides:
    - Async HTTP operations using httpx
    - OpenTelemetry tracing for distributed tracing
    - Prometheus metrics for monitoring
    - Graceful error handling (returns bool, doesn't raise)

    Example:
        settings = get_consul_settings()
        client = ConsulClient(settings)

        success = await client.register_service(
            service_id="my-service-1",
            service_name="my-service",
            address="192.168.1.100",
            port=8000,
            tags=["api", "v1"],
            meta={"version": "1.0.0"},
            check={"TTL": "30s"},
        )

        await client.close()
    """

    def __init__(self, settings: ConsulSettings) -> None:
        """Initialize the Consul client.

        Args:
            settings: ConsulSettings instance with connection configuration.
        """
        self._settings = settings
        self._base_url = settings.base_url
        self._headers = settings.get_auth_headers()

        # Create httpx client with configured timeouts
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=httpx.Timeout(settings.connect_timeout),
            verify=settings.verify_ssl,
        )

        logger.debug(
            "ConsulClient initialized",
            extra={"base_url": self._base_url, "datacenter": settings.datacenter},
        )

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
        start_time = time.perf_counter()

        # Build service registration payload
        payload: dict[str, Any] = {
            "ID": service_id,
            "Name": service_name,
            "Address": address,
            "Port": port,
            "Tags": tags,
            "Meta": meta,
            "Check": check,
        }

        # Add datacenter if configured
        if self._settings.datacenter:
            payload["Datacenter"] = self._settings.datacenter

        with tracer.start_as_current_span("consul.register_service") as span:
            span.set_attribute("consul.service_id", service_id)
            span.set_attribute("consul.service_name", service_name)
            span.set_attribute("consul.address", address)
            span.set_attribute("consul.port", port)

            try:
                response = await self._client.put(
                    "/v1/agent/service/register",
                    json=payload,
                )

                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="register"
                ).observe(duration)

                if response.status_code == 200:
                    span.set_attribute("consul.success", True)
                    service_discovery_registrations_total.labels(status="success").inc()
                    logger.info(
                        "Service registered with Consul",
                        extra={
                            "service_id": service_id,
                            "service_name": service_name,
                            "address": address,
                            "port": port,
                        },
                    )
                    return True
                else:
                    span.set_attribute("consul.success", False)
                    span.set_attribute("consul.status_code", response.status_code)
                    service_discovery_registrations_total.labels(status="failure").inc()
                    service_discovery_errors_total.labels(
                        operation="register", error_type="http_error"
                    ).inc()
                    logger.warning(
                        "Consul registration failed",
                        extra={
                            "service_id": service_id,
                            "status_code": response.status_code,
                            "response": response.text[:200],
                        },
                    )
                    return False

            except httpx.TimeoutException as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="register"
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_registrations_total.labels(status="failure").inc()
                service_discovery_errors_total.labels(
                    operation="register", error_type="timeout"
                ).inc()
                logger.warning(
                    "Consul registration timed out",
                    extra={"service_id": service_id, "error": str(e)},
                )
                return False

            except httpx.HTTPError as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="register"
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_registrations_total.labels(status="failure").inc()
                service_discovery_errors_total.labels(
                    operation="register", error_type="connection"
                ).inc()
                logger.warning(
                    "Consul registration connection error",
                    extra={"service_id": service_id, "error": str(e)},
                )
                return False

    async def deregister_service(self, service_id: str) -> bool:
        """Deregister a service from Consul agent.

        Args:
            service_id: The service instance ID to deregister.

        Returns:
            True if deregistration succeeded, False otherwise.
        """
        start_time = time.perf_counter()

        with tracer.start_as_current_span("consul.deregister_service") as span:
            span.set_attribute("consul.service_id", service_id)

            try:
                response = await self._client.put(
                    f"/v1/agent/service/deregister/{service_id}",
                )

                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="deregister"
                ).observe(duration)

                if response.status_code == 200:
                    span.set_attribute("consul.success", True)
                    service_discovery_deregistrations_total.labels(status="success").inc()
                    logger.info(
                        "Service deregistered from Consul",
                        extra={"service_id": service_id},
                    )
                    return True
                else:
                    span.set_attribute("consul.success", False)
                    span.set_attribute("consul.status_code", response.status_code)
                    service_discovery_deregistrations_total.labels(status="failure").inc()
                    service_discovery_errors_total.labels(
                        operation="deregister", error_type="http_error"
                    ).inc()
                    logger.warning(
                        "Consul deregistration failed",
                        extra={
                            "service_id": service_id,
                            "status_code": response.status_code,
                        },
                    )
                    return False

            except httpx.TimeoutException as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="deregister"
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_deregistrations_total.labels(status="failure").inc()
                service_discovery_errors_total.labels(
                    operation="deregister", error_type="timeout"
                ).inc()
                logger.warning(
                    "Consul deregistration timed out",
                    extra={"service_id": service_id, "error": str(e)},
                )
                return False

            except httpx.HTTPError as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation="deregister"
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_deregistrations_total.labels(status="failure").inc()
                service_discovery_errors_total.labels(
                    operation="deregister", error_type="connection"
                ).inc()
                logger.warning(
                    "Consul deregistration connection error",
                    extra={"service_id": service_id, "error": str(e)},
                )
                return False

    async def _ttl_update(
        self, check_id: str, status: str, note: str | None = None
    ) -> bool:
        """Send TTL check update to Consul.

        Args:
            check_id: The check ID to update.
            status: The status to set (pass, warn, fail).
            note: Optional note to include.

        Returns:
            True if update succeeded, False otherwise.
        """
        start_time = time.perf_counter()
        operation = f"ttl_{status}"

        with tracer.start_as_current_span(f"consul.{operation}") as span:
            span.set_attribute("consul.check_id", check_id)
            span.set_attribute("consul.status", status)

            try:
                # Consul API: PUT /v1/agent/check/{status}/{check_id}
                url = f"/v1/agent/check/{status}/{check_id}"
                params = {"note": note} if note else None

                response = await self._client.put(url, params=params)

                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation=operation
                ).observe(duration)

                if response.status_code == 200:
                    span.set_attribute("consul.success", True)
                    service_discovery_ttl_passes_total.labels(
                        status="success", check_status=status
                    ).inc()
                    logger.debug(
                        "TTL %s sent to Consul", status, extra={"check_id": check_id}
                    )
                    return True
                else:
                    span.set_attribute("consul.success", False)
                    span.set_attribute("consul.status_code", response.status_code)
                    service_discovery_ttl_passes_total.labels(
                        status="failure", check_status=status
                    ).inc()
                    service_discovery_errors_total.labels(
                        operation=operation, error_type="http_error"
                    ).inc()
                    logger.warning(
                        "TTL %s failed",
                        status,
                        extra={
                            "check_id": check_id,
                            "status_code": response.status_code,
                        },
                    )
                    return False

            except httpx.TimeoutException as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation=operation
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_ttl_passes_total.labels(
                    status="failure", check_status=status
                ).inc()
                service_discovery_errors_total.labels(
                    operation=operation, error_type="timeout"
                ).inc()
                logger.warning(
                    "TTL %s timed out",
                    status,
                    extra={"check_id": check_id, "error": str(e)},
                )
                return False

            except httpx.HTTPError as e:
                duration = time.perf_counter() - start_time
                service_discovery_operation_duration_seconds.labels(
                    operation=operation
                ).observe(duration)
                span.set_attribute("consul.success", False)
                span.record_exception(e)
                service_discovery_ttl_passes_total.labels(
                    status="failure", check_status=status
                ).inc()
                service_discovery_errors_total.labels(
                    operation=operation, error_type="connection"
                ).inc()
                logger.warning(
                    "TTL %s connection error",
                    status,
                    extra={"check_id": check_id, "error": str(e)},
                )
                return False

    async def pass_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check pass to mark service as healthy.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL pass succeeded, False otherwise.
        """
        return await self._ttl_update(check_id, "pass", note)

    async def fail_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check fail to mark service as unhealthy.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL fail succeeded, False otherwise.
        """
        return await self._ttl_update(check_id, "fail", note)

    async def warn_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Send TTL check warn to mark service as degraded.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL warn succeeded, False otherwise.
        """
        return await self._ttl_update(check_id, "warn", note)

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._client.aclose()
        logger.debug("ConsulClient closed")
