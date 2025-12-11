"""Tests for RateLimitStateTracker."""

from datetime import UTC, datetime, timedelta

import pytest

from example_service.infra.ratelimit.status import RateLimitProtectionStatus
from example_service.infra.ratelimit.tracker import RateLimitStateTracker


class TestRateLimitStateTracker:
    """Validate state transitions and metrics hooks."""

    def test_initial_state_active(self):
        tracker = RateLimitStateTracker()
        state = tracker.get_state()
        assert state.status == RateLimitProtectionStatus.ACTIVE
        assert state.consecutive_failures == 0

    def test_record_failure_triggers_degraded(self, monkeypatch: pytest.MonkeyPatch):
        tracker = RateLimitStateTracker(failure_threshold=2)
        status_updates: list[str] = []
        error_types: list[str] = []

        import example_service.infra.metrics.tracking as metrics_tracking

        monkeypatch.setattr(
            metrics_tracking,
            "update_rate_limiter_protection_status",
            lambda status: status_updates.append(status),
        )
        monkeypatch.setattr(
            metrics_tracking,
            "track_rate_limiter_redis_error",
            lambda error_type: error_types.append(error_type),
        )

        tracker.record_failure("connection refused")
        assert tracker.get_state().status == RateLimitProtectionStatus.ACTIVE
        tracker.record_failure("connection refused")
        state = tracker.get_state()
        assert state.status == RateLimitProtectionStatus.DEGRADED
        assert state.consecutive_failures == 2
        assert status_updates[-1] == RateLimitProtectionStatus.DEGRADED.value
        assert error_types[-1] == "connection"

    def test_record_success_restores_active(self, monkeypatch: pytest.MonkeyPatch):
        tracker = RateLimitStateTracker(failure_threshold=1)

        import example_service.infra.metrics.tracking as metrics_tracking

        monkeypatch.setattr(
            metrics_tracking,
            "update_rate_limiter_protection_status",
            lambda status: None,
        )
        monkeypatch.setattr(
            metrics_tracking,
            "track_rate_limiter_redis_error",
            lambda error_type: None,
        )

        tracker.record_failure("timeout")
        assert tracker.get_state().status == RateLimitProtectionStatus.DEGRADED

        tracker.record_success()
        state = tracker.get_state()
        assert state.status == RateLimitProtectionStatus.ACTIVE
        assert state.consecutive_failures == 0
        assert state.last_error is None

    def test_mark_disabled(self, monkeypatch: pytest.MonkeyPatch):
        tracker = RateLimitStateTracker()

        import example_service.infra.metrics.tracking as metrics_tracking

        monkeypatch.setattr(
            metrics_tracking,
            "update_rate_limiter_protection_status",
            lambda status: None,
        )

        tracker.mark_disabled()
        state = tracker.get_state()
        assert state.status == RateLimitProtectionStatus.DISABLED
        assert state.since <= datetime.now(UTC) + timedelta(seconds=1)
