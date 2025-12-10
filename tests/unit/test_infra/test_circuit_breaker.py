"""Comprehensive tests for Circuit Breaker pattern implementation.

Tests cover:
- State transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure threshold triggering
- Recovery timeout behavior
- Success threshold in HALF_OPEN state
- Thread-safe operation with asyncio.Lock
- Decorator pattern (@breaker.protected)
- Context manager pattern (async with breaker)
- Manual call pattern (await breaker.call())
- Metrics and statistics tracking
- Exception filtering (expected vs unexpected)
- Edge cases and error conditions

"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from example_service.infra.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class ServiceError(Exception):
    """Test exception for circuit breaker testing."""


class UnexpectedError(Exception):
    """Exception that should not trigger circuit breaker."""


@pytest.fixture
def breaker() -> CircuitBreaker:
    """Create a circuit breaker with default settings for testing."""
    return CircuitBreaker(
        name="test_service",
        failure_threshold=3,
        recovery_timeout=1.0,  # Short timeout for faster tests
        success_threshold=2,
        half_open_max_calls=2,
        expected_exception=ServiceError,
    )


@pytest.fixture
def fast_failing_func() -> Callable[[], None]:
    """Create a function that always raises ServiceError."""

    async def func() -> None:
        msg = "Service unavailable"
        raise ServiceError(msg)

    return func


@pytest.fixture
def successful_func() -> Callable[[], str]:
    """Create a function that always succeeds."""

    async def func() -> str:
        return "success"

    return func


class TestCircuitBreakerInitialization:
    """Test circuit breaker initialization and configuration."""

    def test_initialization_with_defaults(self) -> None:
        """Test circuit breaker initializes with correct default values."""
        breaker = CircuitBreaker(name="test")

        assert breaker.name == "test"
        assert breaker.failure_threshold == 5
        assert breaker.recovery_timeout == 60.0
        assert breaker.success_threshold == 2
        assert breaker.half_open_max_calls == 3
        assert breaker.state == CircuitState.CLOSED
        assert breaker.total_failures == 0
        assert breaker.total_successes == 0
        assert breaker.total_rejections == 0

    def test_initialization_with_custom_values(self) -> None:
        """Test circuit breaker initializes with custom configuration."""
        breaker = CircuitBreaker(
            name="custom",
            failure_threshold=10,
            recovery_timeout=120.0,
            success_threshold=5,
            half_open_max_calls=3,
        )

        assert breaker.failure_threshold == 10
        assert breaker.recovery_timeout == 120.0
        assert breaker.success_threshold == 5
        assert breaker.half_open_max_calls == 3

    def test_initialization_validates_thresholds(self) -> None:
        """Test that initialization validates threshold values."""
        with pytest.raises(ValueError, match="failure_threshold must be greater than 0"):
            CircuitBreaker(name="test", failure_threshold=0)

        with pytest.raises(ValueError, match="recovery_timeout must be greater than 0"):
            CircuitBreaker(name="test", recovery_timeout=0.0)

        with pytest.raises(ValueError, match="success_threshold must be greater than 0"):
            CircuitBreaker(name="test", success_threshold=0)

        with pytest.raises(ValueError, match="half_open_max_calls must be greater than 0"):
            CircuitBreaker(name="test", half_open_max_calls=0)


class TestCircuitBreakerStateProperties:
    """Test circuit breaker state property accessors."""

    def test_is_closed_property(self, breaker: CircuitBreaker) -> None:
        """Test is_closed property correctly reflects state."""
        assert breaker.is_closed
        assert not breaker.is_open
        assert not breaker.is_half_open

    async def test_is_open_property(self, breaker: CircuitBreaker) -> None:
        """Test is_open property correctly reflects state."""
        # Force circuit to open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC)

        assert breaker.is_open
        assert not breaker.is_closed
        assert not breaker.is_half_open

    async def test_is_half_open_property(self, breaker: CircuitBreaker) -> None:
        """Test is_half_open property correctly reflects state."""
        # Force circuit to half-open
        breaker._state = CircuitState.HALF_OPEN

        assert breaker.is_half_open
        assert not breaker.is_closed
        assert not breaker.is_open


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state transitions."""

    async def test_closed_to_open_on_failures(
        self, breaker: CircuitBreaker, fast_failing_func: Callable[[], None]
    ) -> None:
        """Test circuit opens after exceeding failure threshold."""
        assert breaker.state == CircuitState.CLOSED

        # Cause failures up to threshold
        for attempt in range(breaker.failure_threshold):
            expected_exception = (
                ServiceError
                if attempt < breaker.failure_threshold - 1
                else CircuitOpenError
            )
            with pytest.raises(expected_exception):
                await breaker.call(fast_failing_func)

        assert breaker.state == CircuitState.OPEN
        assert breaker.total_failures == breaker.failure_threshold

    async def test_open_to_half_open_after_timeout(self, breaker: CircuitBreaker) -> None:
        """Test circuit transitions to half-open after recovery timeout."""
        # Force circuit to open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC) - timedelta(
            seconds=breaker.recovery_timeout + 1
        )

        # Check state should trigger transition
        async with breaker._lock:
            await breaker._check_state()

        assert breaker.state == CircuitState.HALF_OPEN

    async def test_half_open_to_closed_on_successes(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test circuit closes after success threshold in half-open state."""
        # Set circuit to half-open
        breaker._state = CircuitState.HALF_OPEN

        # Achieve successful calls to meet threshold
        for _ in range(breaker.success_threshold):
            result = await breaker.call(successful_func)
            assert result == "success"

        assert breaker.state == CircuitState.CLOSED
        assert breaker.total_successes == breaker.success_threshold

    async def test_half_open_to_open_on_failure(
        self, breaker: CircuitBreaker, fast_failing_func: Callable[[], None]
    ) -> None:
        """Test circuit reopens on any failure in half-open state."""
        # Set circuit to half-open
        breaker._state = CircuitState.HALF_OPEN
        breaker._failure_count = 0

        # Single failure should reopen circuit
        with pytest.raises(CircuitOpenError):
            await breaker.call(fast_failing_func)

        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerCallProtection:
    """Test circuit breaker call() method."""

    async def test_call_succeeds_when_closed(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test successful call passes through when circuit is closed."""
        result = await breaker.call(successful_func)

        assert result == "success"
        assert breaker.total_successes == 1
        assert breaker.total_failures == 0

    async def test_call_raises_circuit_open_error_when_open(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test call raises CircuitOpenError when circuit is open."""
        # Force circuit to open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC)

        with pytest.raises(CircuitOpenError, match="Circuit breaker 'test_service' is open"):
            await breaker.call(successful_func)

        assert breaker.total_rejections == 1

    async def test_call_records_failures(
        self, breaker: CircuitBreaker, fast_failing_func: Callable[[], None]
    ) -> None:
        """Test call records failures and updates metrics."""
        with pytest.raises(ServiceError):
            await breaker.call(fast_failing_func)

        assert breaker.total_failures == 1
        assert breaker._failure_count == 1

    async def test_call_resets_failure_count_on_success(
        self,
        breaker: CircuitBreaker,
        fast_failing_func: Callable[[], None],
        successful_func: Callable[[], str],
    ) -> None:
        """Test successful call resets failure count in CLOSED state."""
        # Cause some failures (below threshold)
        for _ in range(breaker.failure_threshold - 1):
            with pytest.raises(ServiceError):
                await breaker.call(fast_failing_func)

        assert breaker._failure_count == breaker.failure_threshold - 1

        # Success should reduce failure count
        await breaker.call(successful_func)
        assert breaker._failure_count == breaker.failure_threshold - 2

    async def test_call_with_unexpected_exception(self, breaker: CircuitBreaker) -> None:
        """Test unexpected exceptions don't affect circuit state."""

        async def unexpected_error_func() -> None:
            msg = "Unexpected issue"
            raise UnexpectedError(msg)

        initial_state = breaker.state

        with pytest.raises(UnexpectedError):
            await breaker.call(unexpected_error_func)

        # State should remain unchanged
        assert breaker.state == initial_state
        assert breaker.total_failures == 0


class TestCircuitBreakerDecoratorPattern:
    """Test circuit breaker decorator (@breaker.protected) pattern."""

    async def test_protected_decorator_success(self, breaker: CircuitBreaker) -> None:
        """Test @breaker.protected decorator with successful function."""

        @breaker.protected
        async def fetch_data() -> dict[str, str]:
            return {"status": "ok"}

        result = await fetch_data()

        assert result == {"status": "ok"}
        assert breaker.total_successes == 1

    async def test_protected_decorator_failure(self, breaker: CircuitBreaker) -> None:
        """Test @breaker.protected decorator with failing function."""

        @breaker.protected
        async def fetch_data() -> None:
            msg = "API error"
            raise ServiceError(msg)

        with pytest.raises(ServiceError):
            await fetch_data()

        assert breaker.total_failures == 1

    async def test_protected_decorator_preserves_metadata(self, breaker: CircuitBreaker) -> None:
        """Test @breaker.protected preserves function metadata."""

        @breaker.protected
        async def documented_function() -> str:
            """This is a documented function."""
            return "result"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."

    async def test_call_decorator_alias(self, breaker: CircuitBreaker) -> None:
        """Test __call__ decorator works as alias for protected."""

        @breaker
        async def fetch_data() -> str:
            return "data"

        result = await fetch_data()
        assert result == "data"


class TestCircuitBreakerContextManager:
    """Test circuit breaker context manager (async with) pattern."""

    async def test_context_manager_success(self, breaker: CircuitBreaker) -> None:
        """Test async with context manager with successful operation."""
        async with breaker:
            result = "success"

        assert result == "success"
        assert breaker.total_successes == 1

    async def test_context_manager_failure(self, breaker: CircuitBreaker) -> None:
        """Test async with context manager with failing operation."""
        with pytest.raises(ServiceError):
            async with breaker:
                msg = "Operation failed"
                raise ServiceError(msg)

        assert breaker.total_failures == 1

    async def test_context_manager_raises_when_open(self, breaker: CircuitBreaker) -> None:
        """Test context manager raises CircuitOpenError when circuit is open."""
        # Force circuit to open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC)

        with pytest.raises(CircuitOpenError):
            async with breaker:
                pass  # Should not reach here

    async def test_context_manager_half_open_call_limit(self, breaker: CircuitBreaker) -> None:
        """Test context manager respects half-open call limit."""
        # Set to half-open with calls at limit
        breaker._state = CircuitState.HALF_OPEN
        breaker._half_open_calls = breaker.half_open_max_calls

        with pytest.raises(CircuitOpenError, match="half-open call limit reached"):
            async with breaker:
                pass


class TestCircuitBreakerMetrics:
    """Test circuit breaker metrics and statistics."""

    async def test_get_metrics_initial_state(self, breaker: CircuitBreaker) -> None:
        """Test get_metrics returns correct initial values."""
        metrics = breaker.get_metrics()

        assert metrics["state"] == "closed"
        assert metrics["failure_count"] == 0
        assert metrics["success_count"] == 0
        assert metrics["total_failures"] == 0
        assert metrics["total_successes"] == 0
        assert metrics["total_rejections"] == 0
        assert metrics["last_failure_time"] is None
        assert metrics["failure_rate"] == 0.0

    async def test_get_metrics_tracks_operations(
        self,
        breaker: CircuitBreaker,
        successful_func: Callable[[], str],
        fast_failing_func: Callable[[], None],
    ) -> None:
        """Test get_metrics tracks all operations correctly."""
        # Perform some operations
        await breaker.call(successful_func)
        await breaker.call(successful_func)

        with pytest.raises(ServiceError):
            await breaker.call(fast_failing_func)

        metrics = breaker.get_metrics()

        assert metrics["total_successes"] == 2
        assert metrics["total_failures"] == 1
        assert metrics["failure_rate"] == pytest.approx(1 / 3)
        assert metrics["last_failure_time"] is not None

    async def test_get_metrics_failure_rate_calculation(self, breaker: CircuitBreaker) -> None:
        """Test failure rate is calculated correctly."""
        breaker.total_successes = 7
        breaker.total_failures = 3

        metrics = breaker.get_metrics()
        assert metrics["failure_rate"] == pytest.approx(0.3)

    async def test_get_stats_backward_compatibility(self, breaker: CircuitBreaker) -> None:
        """Test get_stats method for backward compatibility."""
        stats = breaker.get_stats()

        assert "name" in stats
        assert "state" in stats
        assert "failure_count" in stats
        assert stats["name"] == "test_service"


class TestCircuitBreakerReset:
    """Test circuit breaker manual reset functionality."""

    async def test_reset_clears_state(self, breaker: CircuitBreaker) -> None:
        """Test reset clears all state and metrics."""
        # Set some state
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5
        breaker.total_failures = 10
        breaker.total_successes = 5
        breaker.total_rejections = 3

        await breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        assert breaker.total_failures == 0
        assert breaker.total_successes == 0
        assert breaker.total_rejections == 0

    async def test_reset_allows_immediate_calls(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test reset allows calls immediately after resetting open circuit."""
        # Open the circuit
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC)

        await breaker.reset()

        # Should be able to call immediately
        result = await breaker.call(successful_func)
        assert result == "success"


class TestCircuitBreakerConcurrency:
    """Test circuit breaker behavior under concurrent access."""

    async def test_concurrent_calls_thread_safe(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test concurrent calls are handled safely with lock."""
        # Execute multiple concurrent calls
        tasks = [breaker.call(successful_func) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert all(r == "success" for r in results)
        assert breaker.total_successes == 10

    async def test_concurrent_failures_counted_correctly(
        self, breaker: CircuitBreaker, fast_failing_func: Callable[[], None]
    ) -> None:
        """Test concurrent failures are counted correctly."""
        # Execute failures sequentially to avoid circuit opening during test
        for _ in range(breaker.failure_threshold - 1):
            with pytest.raises(ServiceError):
                await breaker.call(fast_failing_func)

        # Total failures should be recorded
        assert breaker.total_failures == breaker.failure_threshold - 1
        assert breaker.state == CircuitState.CLOSED  # Not yet open


class TestCircuitBreakerHalfOpenState:
    """Test circuit breaker half-open state behavior."""

    async def test_half_open_limits_concurrent_calls(self, breaker: CircuitBreaker) -> None:
        """Test half-open state limits concurrent calls."""
        breaker._state = CircuitState.HALF_OPEN
        breaker._half_open_calls = 0

        # First calls up to limit should succeed
        for i in range(breaker.half_open_max_calls):
            async with breaker._lock:
                await breaker._check_state()
                breaker._half_open_calls += 1
            assert breaker._half_open_calls == i + 1

        # Next call should be rejected
        with pytest.raises(CircuitOpenError, match="half-open call limit reached"):
            async with breaker:
                pass

    async def test_half_open_success_progression(
        self, breaker: CircuitBreaker, successful_func: Callable[[], str]
    ) -> None:
        """Test half-open state progresses to closed on successes."""
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 0

        # Perform successful calls up to threshold
        for _i in range(breaker.success_threshold):
            result = await breaker.call(successful_func)
            assert result == "success"

        # Should have transitioned to closed
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error conditions."""

    async def test_recovery_timeout_edge_case(self, breaker: CircuitBreaker) -> None:
        """Test recovery timeout at exact boundary."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = datetime.now(UTC) - timedelta(seconds=breaker.recovery_timeout)

        async with breaker._lock:
            await breaker._check_state()

        # Should transition exactly at timeout boundary
        assert breaker.state == CircuitState.HALF_OPEN

    async def test_zero_failure_rate_with_no_calls(self, breaker: CircuitBreaker) -> None:
        """Test failure rate is 0 when no calls have been made."""
        metrics = breaker.get_metrics()
        assert metrics["failure_rate"] == 0.0

    async def test_exception_in_decorator_propagates(self, breaker: CircuitBreaker) -> None:
        """Test exceptions in decorated functions propagate correctly."""

        @breaker.protected
        async def failing_function() -> None:
            msg = "Expected failure"
            raise ServiceError(msg)

        with pytest.raises(ServiceError, match="Expected failure"):
            await failing_function()


class TestCircuitBreakerIntegration:
    """Integration tests for complete circuit breaker workflows."""

    async def test_full_circuit_lifecycle(
        self,
        breaker: CircuitBreaker,
        fast_failing_func: Callable[[], None],
        successful_func: Callable[[], str],
    ) -> None:
        """Test complete circuit breaker lifecycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        # 1. Start in CLOSED state
        assert breaker.state == CircuitState.CLOSED

        # 2. Cause failures to open circuit
        for attempt in range(breaker.failure_threshold):
            expected_exception = (
                ServiceError
                if attempt < breaker.failure_threshold - 1
                else CircuitOpenError
            )
            with pytest.raises(expected_exception):
                await breaker.call(fast_failing_func)

        assert breaker.state == CircuitState.OPEN

        # 3. Wait for recovery timeout
        breaker._last_failure_time = datetime.now(UTC) - timedelta(
            seconds=breaker.recovery_timeout + 1
        )

        # 4. Check state to trigger HALF_OPEN transition
        async with breaker._lock:
            await breaker._check_state()

        assert breaker.state == CircuitState.HALF_OPEN

        # 5. Perform successful calls to close circuit
        for _ in range(breaker.success_threshold):
            await breaker.call(successful_func)

        assert breaker.state == CircuitState.CLOSED

    async def test_realistic_service_degradation_scenario(self) -> None:
        """Test realistic scenario of service degradation and recovery."""
        # Create breaker with realistic settings
        service_breaker = CircuitBreaker(
            name="payment_api",
            failure_threshold=5,
            recovery_timeout=2.0,
            success_threshold=3,
            half_open_max_calls=3,  # Allow 3 calls in half-open to meet success threshold
            expected_exception=ServiceError,
        )

        call_count = 0

        async def payment_api_call() -> str:
            nonlocal call_count
            call_count += 1

            # Simulate intermittent failures
            if call_count <= 5:
                msg = "Service degraded"
                raise ServiceError(msg)
            return "Payment processed"

        # Calls 1-5: Failures that open the circuit
        for attempt in range(5):
            expected_exception = ServiceError if attempt < 4 else CircuitOpenError
            with pytest.raises(expected_exception):
                await service_breaker.call(payment_api_call)

        assert service_breaker.is_open

        # Attempt during open state should be rejected
        with pytest.raises(CircuitOpenError):
            await service_breaker.call(payment_api_call)

        # Simulate recovery timeout passage
        service_breaker._last_failure_time = datetime.now(UTC) - timedelta(seconds=3)

        # Calls 6-8: Successful calls that close circuit
        for _ in range(3):
            result = await service_breaker.call(payment_api_call)
            assert result == "Payment processed"

        assert service_breaker.is_closed
