"""Mock Consul client for testing without a real Consul instance.

This module provides a MockConsulClient that implements ConsulClientProtocol
and stores all state in memory, making it ideal for unit tests.

Usage in tests:
    from example_service.infra.discovery.mock_client import MockConsulClient

    @pytest.fixture
    def mock_consul():
        return MockConsulClient()

    async def test_service_registration(mock_consul):
        success = await mock_consul.register_service(
            service_id="test-1",
            service_name="test-service",
            address="127.0.0.1",
            port=8000,
            tags=["api"],
            meta={"version": "1.0"},
            check={"TTL": "30s"},
        )
        assert success
        assert "test-1" in mock_consul.services
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TTLState(str, Enum):
    """TTL check states in Consul."""

    PASSING = "passing"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ServiceRecord:
    """Record of a registered service for inspection in tests."""

    service_id: str
    service_name: str
    address: str
    port: int
    tags: list[str]
    meta: dict[str, str]
    check: dict[str, Any]


@dataclass
class CallRecord:
    """Record of a method call for assertion in tests."""

    method: str
    args: dict[str, Any]
    success: bool


class MockConsulClient:
    """In-memory mock Consul client for testing.

    This class implements ConsulClientProtocol and stores all state
    in memory, allowing tests to:
    - Verify registration/deregistration behavior
    - Inspect service records
    - Check TTL state transitions
    - Review call history

    Attributes:
        services: Dictionary of registered services by service_id.
        ttl_states: Dictionary of TTL check states by check_id.
        call_history: List of all method calls for assertion.
        fail_next_call: Set to True to simulate a failure on next call.
        closed: Whether close() has been called.
    """

    def __init__(self) -> None:
        """Initialize the mock client with empty state."""
        self.services: dict[str, ServiceRecord] = {}
        self.ttl_states: dict[str, TTLState] = {}
        self.call_history: list[CallRecord] = []
        self.fail_next_call: bool = False
        self.closed: bool = False

    def _should_fail(self) -> bool:
        """Check if the next call should fail and reset flag."""
        if self.fail_next_call:
            self.fail_next_call = False
            return True
        return False

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
        """Register a service in memory.

        Args:
            service_id: Unique identifier for this service instance.
            service_name: Logical name of the service.
            address: IP address or hostname to advertise.
            port: Port number to advertise.
            tags: List of tags for filtering and routing.
            meta: Key-value metadata for the service.
            check: Health check definition (TTL or HTTP).

        Returns:
            True if registration succeeded (unless fail_next_call is set).
        """
        call_args = {
            "service_id": service_id,
            "service_name": service_name,
            "address": address,
            "port": port,
            "tags": tags,
            "meta": meta,
            "check": check,
        }

        if self._should_fail():
            self.call_history.append(CallRecord("register_service", call_args, False))
            logger.debug("MockConsulClient: register_service failed (simulated)")
            return False

        self.services[service_id] = ServiceRecord(
            service_id=service_id,
            service_name=service_name,
            address=address,
            port=port,
            tags=list(tags),
            meta=dict(meta),
            check=dict(check),
        )

        # Initialize TTL state if TTL check
        if "TTL" in check:
            check_id = f"service:{service_id}"
            self.ttl_states[check_id] = TTLState.PASSING

        self.call_history.append(CallRecord("register_service", call_args, True))
        logger.debug("MockConsulClient: registered service %s", service_id)
        return True

    async def deregister_service(self, service_id: str) -> bool:
        """Deregister a service from memory.

        Args:
            service_id: The service instance ID to deregister.

        Returns:
            True if deregistration succeeded.
        """
        call_args = {"service_id": service_id}

        if self._should_fail():
            self.call_history.append(CallRecord("deregister_service", call_args, False))
            logger.debug("MockConsulClient: deregister_service failed (simulated)")
            return False

        # Remove service and its TTL state
        self.services.pop(service_id, None)
        check_id = f"service:{service_id}"
        self.ttl_states.pop(check_id, None)

        self.call_history.append(CallRecord("deregister_service", call_args, True))
        logger.debug("MockConsulClient: deregistered service %s", service_id)
        return True

    async def pass_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Mark TTL check as passing.

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL pass succeeded.
        """
        call_args = {"check_id": check_id, "note": note}

        if self._should_fail():
            self.call_history.append(CallRecord("pass_ttl", call_args, False))
            return False

        self.ttl_states[check_id] = TTLState.PASSING
        self.call_history.append(CallRecord("pass_ttl", call_args, True))
        logger.debug("MockConsulClient: TTL pass for %s", check_id)
        return True

    async def fail_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Mark TTL check as failing (critical).

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL fail succeeded.
        """
        call_args = {"check_id": check_id, "note": note}

        if self._should_fail():
            self.call_history.append(CallRecord("fail_ttl", call_args, False))
            return False

        self.ttl_states[check_id] = TTLState.CRITICAL
        self.call_history.append(CallRecord("fail_ttl", call_args, True))
        logger.debug("MockConsulClient: TTL fail for %s", check_id)
        return True

    async def warn_ttl(self, check_id: str, note: str | None = None) -> bool:
        """Mark TTL check as warning (degraded).

        Args:
            check_id: The check ID (typically "service:{service_id}").
            note: Optional note to include with the status update.

        Returns:
            True if the TTL warn succeeded.
        """
        call_args = {"check_id": check_id, "note": note}

        if self._should_fail():
            self.call_history.append(CallRecord("warn_ttl", call_args, False))
            return False

        self.ttl_states[check_id] = TTLState.WARNING
        self.call_history.append(CallRecord("warn_ttl", call_args, True))
        logger.debug("MockConsulClient: TTL warn for %s", check_id)
        return True

    async def close(self) -> None:
        """Mark the client as closed."""
        self.closed = True
        self.call_history.append(CallRecord("close", {}, True))
        logger.debug("MockConsulClient: closed")

    # ──────────────────────────────────────────────────────────────
    # Test helper methods
    # ──────────────────────────────────────────────────────────────

    def get_service(self, service_id: str) -> ServiceRecord | None:
        """Get a registered service by ID (test helper).

        Args:
            service_id: The service ID to look up.

        Returns:
            ServiceRecord if found, None otherwise.
        """
        return self.services.get(service_id)

    def get_ttl_state(self, service_id: str) -> TTLState | None:
        """Get TTL state for a service (test helper).

        Args:
            service_id: The service ID to look up.

        Returns:
            TTLState if found, None otherwise.
        """
        check_id = f"service:{service_id}"
        return self.ttl_states.get(check_id)

    def get_calls(self, method: str | None = None) -> list[CallRecord]:
        """Get call history, optionally filtered by method (test helper).

        Args:
            method: Optional method name to filter by.

        Returns:
            List of CallRecord objects.
        """
        if method is None:
            return list(self.call_history)
        return [c for c in self.call_history if c.method == method]

    def reset(self) -> None:
        """Reset all state (test helper).

        Clears services, TTL states, call history, and flags.
        """
        self.services.clear()
        self.ttl_states.clear()
        self.call_history.clear()
        self.fail_next_call = False
        self.closed = False
