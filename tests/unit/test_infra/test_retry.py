"""Unit tests for retry utility and circuit breaker."""
from __future__ import annotations

import pytest

from example_service.utils.retry import CircuitBreaker, RetryError, retry


@pytest.mark.unit
class TestRetryDecorator:
    """Test suite for retry decorator."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_first_attempt(self):
        """Test that retry decorator doesn't retry on success."""
        call_count = 0

        @retry(max_attempts=3)
        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_func()
        assert result == "success"
        assert call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_retries(self):
        """Test that retry decorator retries until success."""
        call_count = 0

        @retry(max_attempts=3, initial_delay=0.01)
        async def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Not yet")
            return "success"

        result = await eventually_successful()
        assert result == "success"
        assert call_count == 3  # Called 3 times

    @pytest.mark.asyncio
    async def test_retry_fails_after_max_attempts(self):
        """Test that retry raises RetryError after max attempts."""
        call_count = 0

        @retry(max_attempts=3, initial_delay=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(RetryError) as exc_info:
            await always_fails()

        assert call_count == 3
        assert "after 3 attempts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_only_retries_specified_exceptions(self):
        """Test that retry only retries specified exception types."""
        call_count = 0

        @retry(max_attempts=3, initial_delay=0.01, exceptions=(ValueError,))
        async def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retryable")

        # Should raise TypeError immediately, not retry
        with pytest.raises(TypeError):
            await raises_type_error()

        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_retry_with_jitter(self):
        """Test that retry with jitter works."""
        @retry(max_attempts=2, initial_delay=0.01, jitter=True)
        async def fails_once():
            raise ValueError("Fail")

        # Should eventually fail, but test that jitter doesn't break it
        with pytest.raises(RetryError):
            await fails_once()

    def test_retry_with_sync_function(self):
        """Test that retry works with synchronous functions."""
        call_count = 0

        @retry(max_attempts=3, initial_delay=0.01)
        def sync_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Fail")
            return "success"

        result = sync_function()
        assert result == "success"
        assert call_count == 2


@pytest.mark.unit
class TestCircuitBreaker:
    """Test suite for circuit breaker."""

    def test_circuit_breaker_initial_state_closed(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        # Define a function that always fails
        def failing_func():
            raise ValueError("test error")

        # Call until threshold
        for _ in range(2):
            try:
                cb.call(failing_func)
            except ValueError:
                pass

        assert cb.state == "CLOSED"
        assert cb.failure_count == 2

        # Third failure should open circuit
        try:
            cb.call(failing_func)
        except ValueError:
            pass

        assert cb.state == "OPEN"
        assert cb.failure_count == 3

    def test_circuit_breaker_resets_on_success(self):
        """Test circuit breaker resets failure count on success."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        # Fail twice
        def failing_func():
            raise ValueError("test")

        for _ in range(2):
            try:
                cb.call(failing_func)
            except ValueError:
                pass

        assert cb.failure_count == 2

        # Succeed
        def success_func():
            return "success"

        result = cb.call(success_func)
        assert result == "success"
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_transitions_to_half_open(self):
        """Test circuit breaker transitions from open to half-open after timeout."""
        import asyncio
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        # Open the circuit
        def failing_func():
            raise ValueError("test")

        for _ in range(2):
            try:
                cb.call(failing_func)
            except ValueError:
                pass

        assert cb.state == "OPEN"

        # Immediately trying to call should fail
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            cb.call(lambda: "test")

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Next successful call should transition to half-open then closed
        def success_func():
            return "recovered"

        result = cb.call(success_func)
        assert result == "recovered"
        assert cb.state == "CLOSED"

    def test_circuit_breaker_respects_exception_filter(self):
        """Test circuit breaker only counts specified exceptions."""
        cb = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=1.0,
            expected_exception=ValueError,
        )

        # TypeError should not be caught or count
        def type_error_func():
            raise TypeError("test")

        # TypeError passes through but doesn't count
        with pytest.raises(TypeError):
            cb.call(type_error_func)

        assert cb.failure_count == 0

        # ValueError should count
        def value_error_func():
            raise ValueError("test")

        for _ in range(2):
            try:
                cb.call(value_error_func)
            except ValueError:
                pass

        assert cb.state == "OPEN"
        assert cb.failure_count == 2
