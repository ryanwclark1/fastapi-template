"""Tests for RateLimiterHealthProvider."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers.rate_limit import (
    RateLimiterHealthProvider,
)
from example_service.infra.ratelimit.status import (
    RateLimitProtectionState,
    RateLimitProtectionStatus,
)


class FakeTracker:
    """Simple tracker implementation for testing."""

    def __init__(self, state: RateLimitProtectionState) -> None:
        self._state = state

    def set_state(self, state: RateLimitProtectionState) -> None:
        self._state = state

    def get_state(self) -> RateLimitProtectionState:
        return self._state


@pytest.mark.asyncio
class TestRateLimiterHealthProvider:
    """Exercise all protection status branches."""

    async def test_active_status(self) -> None:
        state = RateLimitProtectionState(
            status=RateLimitProtectionStatus.ACTIVE,
            since=datetime.fromtimestamp(0, UTC),
            consecutive_failures=0,
        )
        provider = RateLimiterHealthProvider(FakeTracker(state))

        result = await provider.check_health()

        assert provider.name == "rate_limiter"
        assert result.status == HealthStatus.HEALTHY
        assert result.metadata["protection_status"] == "active"
        assert result.metadata["status_since"] == state.since.isoformat()

    async def test_degraded_status(self) -> None:
        state = RateLimitProtectionState(
            status=RateLimitProtectionStatus.DEGRADED,
            since=datetime.now(UTC),
            consecutive_failures=4,
            last_error="Redis timeout",
        )
        provider = RateLimiterHealthProvider(FakeTracker(state))

        result = await provider.check_health()

        assert result.status == HealthStatus.DEGRADED
        assert "fail-open mode" in result.message
        assert result.metadata["consecutive_failures"] == 4
        assert result.metadata["last_error"] == "Redis timeout"

    async def test_disabled_status(self) -> None:
        state = RateLimitProtectionState(
            status=RateLimitProtectionStatus.DISABLED,
            since=datetime.now(UTC),
        )
        provider = RateLimiterHealthProvider(FakeTracker(state))

        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert "disabled" in result.message.lower()

    async def test_unknown_status_defaults_to_unhealthy(self) -> None:
        class UnknownStatus:
            value = "unknown"

            def __hash__(self) -> int:
                return hash(self.value)

        state = RateLimitProtectionState(
            status=UnknownStatus(),  # type: ignore[arg-type]
            since=datetime.now(UTC),
        )
        provider = RateLimiterHealthProvider(FakeTracker(state))

        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert result.metadata["protection_status"] == "unknown"
