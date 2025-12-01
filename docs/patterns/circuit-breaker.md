# Circuit Breaker Pattern - Production-Ready Implementation

## Overview

The Circuit Breaker pattern is a resilience pattern that prevents cascading failures in distributed systems. This implementation provides production-ready circuit breaker functionality based on the [accent-ai](https://github.com/Acliad/accent-ai) library patterns.

## Features

✅ **Three States**: CLOSED, OPEN, HALF_OPEN with automatic state transitions
✅ **Multiple Usage Patterns**: Decorator, context manager, and direct call
✅ **Thread-Safe**: Uses `asyncio.Lock` for concurrent access protection
✅ **Configurable Thresholds**: Customize failure/success thresholds and timeouts
✅ **Automatic Recovery**: Exponential backoff with configurable recovery timeout
✅ **Comprehensive Metrics**: Track failures, successes, rejections, and failure rate
✅ **Observable**: Structured logging for all state changes and events
✅ **Exception Filtering**: Choose which exceptions trigger the circuit
✅ **Modern Python**: Type hints, ParamSpec, StrEnum, and Python 3.13+ patterns

## Installation

The circuit breaker is included in the fastapi-template infrastructure layer:

```python
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError
```

## Quick Start

### Basic Usage - Decorator Pattern

```python
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError
import httpx

# Create circuit breaker
payment_breaker = CircuitBreaker(
    name="payment_service",
    failure_threshold=5,
    recovery_timeout=60.0,
    success_threshold=2,
)

# Protect function with decorator
@payment_breaker.protected
async def charge_payment(amount: float) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.payment.com/charge",
            json={"amount": amount}
        )
        response.raise_for_status()
        return response.json()

# Use with error handling
try:
    result = await charge_payment(100.0)
    print(f"Payment successful: {result}")
except CircuitOpenError:
    print("Payment service unavailable, please try again later")
except httpx.HTTPError as e:
    print(f"Payment failed: {e}")
```

### Context Manager Pattern

```python
async def fetch_data():
    async with circuit_breaker:
        # Protected operation
        data = await external_api_call()
        return data
```

### Direct Call Pattern

```python
async def operation():
    return await api_call()

result = await circuit_breaker.call(operation)
```

## Configuration

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Required | Unique identifier for the circuit breaker |
| `failure_threshold` | `int` | `5` | Consecutive failures before opening circuit |
| `recovery_timeout` | `float` | `60.0` | Seconds to wait before attempting recovery |
| `success_threshold` | `int` | `2` | Successes needed in HALF_OPEN to close circuit |
| `half_open_max_calls` | `int` | `3` | Max concurrent calls in HALF_OPEN state |
| `expected_exception` | `type[Exception]` | `Exception` | Exception type(s) that trigger the circuit |

### Example Configuration

```python
# Strict circuit breaker for critical operations
critical_breaker = CircuitBreaker(
    name="critical_service",
    failure_threshold=2,      # Open after 2 failures
    recovery_timeout=120.0,   # Wait 2 minutes before retry
    success_threshold=3,      # Need 3 successes to close
    half_open_max_calls=1,    # Very cautious recovery
    expected_exception=httpx.HTTPError,  # Only HTTP errors trigger
)

# Lenient circuit breaker for non-critical operations
lenient_breaker = CircuitBreaker(
    name="cache_service",
    failure_threshold=10,     # More tolerant
    recovery_timeout=30.0,    # Quick recovery attempts
    success_threshold=2,      # Easy to close
    half_open_max_calls=5,    # Allow more test calls
)
```

## State Machine

### States

```
┌─────────┐
│ CLOSED  │ ◄──────────────────────────┐
└─────────┘                            │
     │                                 │
     │ failures ≥ threshold            │ successes ≥ threshold
     ▼                                 │
┌─────────┐                       ┌────────────┐
│  OPEN   │ ─────────────────────►│ HALF_OPEN  │
└─────────┘   recovery_timeout    └────────────┘
                                        │
                                        │ any failure
                                        ▼
                                   (back to OPEN)
```

### State Descriptions

**CLOSED** (Normal Operation)
- All requests pass through
- Failures are counted
- Success resets failure count
- Opens when `failure_count ≥ failure_threshold`

**OPEN** (Failing Fast)
- All requests are rejected with `CircuitOpenError`
- No actual calls are made
- After `recovery_timeout`, transitions to HALF_OPEN

**HALF_OPEN** (Testing Recovery)
- Limited requests allowed (`half_open_max_calls`)
- Success increments success counter
- Any failure immediately reopens circuit
- Closes when `success_count ≥ success_threshold`

## Usage Patterns

### Pattern 1: External API Protection

```python
import httpx
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError

api_breaker = CircuitBreaker(
    name="external_api",
    failure_threshold=5,
    recovery_timeout=60.0,
    expected_exception=httpx.HTTPError,
)

@api_breaker.protected
async def call_external_api(endpoint: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/{endpoint}")
        response.raise_for_status()
        return response.json()

# Usage with fallback
try:
    data = await call_external_api("users/123")
except CircuitOpenError:
    # Service is down, use fallback
    data = await get_cached_data("users/123")
```

### Pattern 2: Database Connection Resilience

```python
from sqlalchemy.ext.asyncio import AsyncSession
from example_service.infra.resilience import CircuitBreaker

db_breaker = CircuitBreaker(
    name="database",
    failure_threshold=3,
    recovery_timeout=30.0,
)

async def fetch_user(session: AsyncSession, user_id: int):
    async with db_breaker:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
```

### Pattern 3: Service-to-Service Communication

```python
class UserServiceClient:
    def __init__(self):
        self.breaker = CircuitBreaker(
            name="user_service",
            failure_threshold=5,
            recovery_timeout=60.0,
        )

    async def get_user(self, user_id: int) -> dict:
        @self.breaker.protected
        async def _fetch():
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://user-service/users/{user_id}"
                )
                response.raise_for_status()
                return response.json()

        return await _fetch()

    def health_check(self) -> dict:
        return self.breaker.get_metrics()
```

### Pattern 4: Multiple Breakers per Service

```python
class PaymentServiceClient:
    def __init__(self):
        # Separate breakers for different operation types
        self.read_breaker = CircuitBreaker(
            name="payment_read",
            failure_threshold=10,  # More tolerant
            recovery_timeout=30.0,
        )

        self.write_breaker = CircuitBreaker(
            name="payment_write",
            failure_threshold=3,   # Less tolerant
            recovery_timeout=60.0,
        )

    async def get_transaction(self, txn_id: str):
        return await self.read_breaker.call(self._fetch_transaction, txn_id)

    async def create_charge(self, amount: float):
        return await self.write_breaker.call(self._process_charge, amount)
```

## Error Handling

### Exception Types

**`CircuitOpenError`**: Simple, lightweight exception for circuit open state
```python
try:
    result = await breaker.call(operation)
except CircuitOpenError as e:
    logger.warning(f"Circuit breaker prevented call: {e}")
    # Implement fallback logic
```

**`CircuitBreakerOpenException`**: FastAPI-compatible exception with HTTP semantics
```python
from example_service.core.exceptions import CircuitBreakerOpenException

try:
    result = await operation()
except CircuitBreakerOpenException as e:
    # Returns 503 Service Unavailable with RFC 7807 details
    raise
```

### Fallback Strategies

**1. Return Cached Data**
```python
try:
    data = await fetch_from_api()
except CircuitOpenError:
    data = await get_from_cache()
```

**2. Queue for Later Processing**
```python
try:
    await process_payment(amount)
except CircuitOpenError:
    await queue_payment_for_retry(amount)
    return {"status": "pending"}
```

**3. Use Backup Service**
```python
try:
    result = await primary_service.process()
except CircuitOpenError:
    result = await backup_service.process()
```

**4. Graceful Degradation**
```python
try:
    enriched_data = await enrichment_service.enrich(data)
except CircuitOpenError:
    # Continue with unenriched data
    enriched_data = data
```

## Metrics and Monitoring

### Get Current Metrics

```python
metrics = breaker.get_metrics()

print(f"State: {metrics['state']}")
print(f"Failure Rate: {metrics['failure_rate']:.2%}")
print(f"Total Failures: {metrics['total_failures']}")
print(f"Total Successes: {metrics['total_successes']}")
print(f"Total Rejections: {metrics['total_rejections']}")
print(f"Last Failure: {metrics['last_failure_time']}")
```

### Metrics Dictionary

```python
{
    'state': 'closed',           # Current state: closed/open/half_open
    'failure_count': 0,          # Current consecutive failures
    'success_count': 0,          # Current consecutive successes (in HALF_OPEN)
    'total_failures': 10,        # Lifetime total failures
    'total_successes': 100,      # Lifetime total successes
    'total_rejections': 5,       # Lifetime total rejected calls
    'last_failure_time': '2025-12-01T10:30:00+00:00',  # ISO 8601 timestamp
    'failure_rate': 0.09         # Ratio: failures / (failures + successes)
}
```

### Health Check Integration

```python
from fastapi import APIRouter, Response

router = APIRouter()

@router.get("/health/circuit-breakers")
async def circuit_breaker_health():
    """Health endpoint for circuit breaker monitoring."""
    breakers = {
        "payment": payment_breaker.get_metrics(),
        "user_service": user_breaker.get_metrics(),
        "database": db_breaker.get_metrics(),
    }

    # Check if any circuit is open
    all_closed = all(
        b["state"] == "closed"
        for b in breakers.values()
    )

    return {
        "status": "healthy" if all_closed else "degraded",
        "breakers": breakers,
    }
```

### Prometheus Metrics Integration

The circuit breaker automatically exports Prometheus metrics:

```python
from example_service.infra.metrics.tracking import (
    track_circuit_breaker_failure,
    track_circuit_breaker_success,
    track_circuit_breaker_state_change,
    update_circuit_breaker_state,
)

# Metrics are automatically tracked:
# - circuit_breaker_state{name="payment_service"}
# - circuit_breaker_failures_total{name="payment_service"}
# - circuit_breaker_successes_total{name="payment_service"}
# - circuit_breaker_state_changes_total{name="payment_service", from_state="closed", to_state="open"}
```

## Testing

### Unit Testing

```python
import pytest
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError

@pytest.fixture
def breaker():
    return CircuitBreaker(
        name="test",
        failure_threshold=3,
        recovery_timeout=1.0,  # Short timeout for tests
        success_threshold=2,
    )

async def test_circuit_opens_on_failures(breaker):
    """Test circuit opens after threshold failures."""

    async def failing_func():
        raise ValueError("Simulated failure")

    # Trigger failures
    for _ in range(3):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    # Circuit should be open
    assert breaker.is_open

    # Next call should be rejected
    with pytest.raises(CircuitOpenError):
        await breaker.call(failing_func)

async def test_circuit_recovery(breaker):
    """Test circuit recovers after timeout."""
    from datetime import UTC, datetime, timedelta

    # Open the circuit
    breaker._state = CircuitState.OPEN
    breaker._last_failure_time = datetime.now(UTC) - timedelta(seconds=2)

    # Should transition to half-open
    async with breaker._lock:
        await breaker._check_state()

    assert breaker.is_half_open
```

### Integration Testing

```python
async def test_circuit_breaker_with_real_service():
    """Test circuit breaker with real external service."""
    breaker = CircuitBreaker(
        name="test_api",
        failure_threshold=3,
        recovery_timeout=5.0,
    )

    @breaker.protected
    async def call_api():
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8080/test")
            response.raise_for_status()
            return response.json()

    # Test normal operation
    result = await call_api()
    assert result is not None

    # Verify metrics
    metrics = breaker.get_metrics()
    assert metrics["total_successes"] == 1
    assert metrics["state"] == "closed"
```

## Best Practices

### 1. Choose Appropriate Thresholds

```python
# Critical operations: Strict thresholds
critical_breaker = CircuitBreaker(
    name="payment",
    failure_threshold=2,      # Fail fast
    recovery_timeout=120.0,   # Long recovery
    success_threshold=3,      # High confidence needed
)

# Non-critical operations: Lenient thresholds
cache_breaker = CircuitBreaker(
    name="cache",
    failure_threshold=10,     # More tolerant
    recovery_timeout=30.0,    # Quick recovery
    success_threshold=2,      # Easy to close
)
```

### 2. Use Specific Exception Types

```python
# Only specific exceptions trigger circuit
breaker = CircuitBreaker(
    name="api",
    expected_exception=httpx.HTTPError,  # Network errors
    # Validation errors, business logic errors won't trigger
)
```

### 3. Implement Fallback Strategies

```python
async def resilient_operation():
    try:
        return await primary_service()
    except CircuitOpenError:
        return await fallback_service()
```

### 4. Monitor Circuit Breaker Health

```python
async def monitor_breakers():
    """Periodic health monitoring."""
    while True:
        for breaker in [payment_breaker, api_breaker, db_breaker]:
            metrics = breaker.get_metrics()
            if metrics["state"] == "open":
                await send_alert(f"Circuit {breaker.name} is open!")
            if metrics["failure_rate"] > 0.5:
                await send_warning(f"High failure rate: {breaker.name}")
        await asyncio.sleep(60)
```

### 5. Reset Carefully

```python
# Only reset manually for administrative actions
# Prefer natural recovery through HALF_OPEN state
async def admin_reset(breaker_name: str):
    """Administrative reset of circuit breaker."""
    breaker = get_breaker(breaker_name)
    await breaker.reset()
    logger.warning(f"Circuit breaker {breaker_name} manually reset")
```

## Advanced Usage

### Custom Circuit Breaker Factory

```python
from typing import Protocol

class ServiceConfig(Protocol):
    failure_threshold: int
    recovery_timeout: float

def create_service_breaker(
    service_name: str,
    config: ServiceConfig,
) -> CircuitBreaker:
    """Factory for creating standardized circuit breakers."""
    return CircuitBreaker(
        name=f"{service_name}_service",
        failure_threshold=config.failure_threshold,
        recovery_timeout=config.recovery_timeout,
        success_threshold=2,
        expected_exception=httpx.HTTPError,
    )
```

### Global Circuit Breaker Registry

```python
class CircuitBreakerRegistry:
    """Global registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def register(self, breaker: CircuitBreaker) -> None:
        self._breakers[breaker.name] = breaker

    def get(self, name: str) -> CircuitBreaker:
        return self._breakers[name]

    def get_all_metrics(self) -> dict[str, dict]:
        return {
            name: breaker.get_metrics()
            for name, breaker in self._breakers.items()
        }

    async def reset_all(self) -> None:
        """Emergency: Reset all circuit breakers."""
        for breaker in self._breakers.values():
            await breaker.reset()

# Global registry
circuit_breaker_registry = CircuitBreakerRegistry()
```

## Performance Considerations

### Lock Contention

The circuit breaker uses `asyncio.Lock` to protect state. Most operations (checking state, recording success/failure) acquire and quickly release the lock. The actual protected operation runs outside the lock to minimize contention.

### Memory Overhead

Each circuit breaker instance maintains minimal state:
- Configuration parameters (5 values)
- State counters (3 integers)
- Metrics (3 integers)
- One datetime object
- One asyncio.Lock

Typical memory per instance: ~1KB

### Recommendations

- Reuse circuit breakers across requests (create once, use many times)
- Don't create new circuit breakers per request
- Use separate breakers for independent services
- Share breakers for identical downstream dependencies

## Migration Guide

### From Existing Implementation

If you have an existing circuit breaker implementation:

```python
# Old implementation
from old_module import OldCircuitBreaker

old_breaker = OldCircuitBreaker(
    name="service",
    threshold=5,
    timeout=60,
)

# New implementation
from example_service.infra.resilience import CircuitBreaker

new_breaker = CircuitBreaker(
    name="service",
    failure_threshold=5,      # Was: threshold
    recovery_timeout=60.0,    # Was: timeout
    success_threshold=2,      # New: configure recovery
    half_open_max_calls=3,    # New: control test phase
)
```

## Troubleshooting

### Circuit Opens Too Frequently

**Problem**: Circuit opens after just a few failures

**Solutions**:
- Increase `failure_threshold`
- Verify exception types are correctly configured
- Check if transient errors are being handled properly

```python
# Before: Too sensitive
breaker = CircuitBreaker(failure_threshold=2)

# After: More tolerant
breaker = CircuitBreaker(
    failure_threshold=5,
    expected_exception=httpx.TimeoutException,  # Only timeouts
)
```

### Circuit Never Closes

**Problem**: Circuit stays open even after service recovers

**Solutions**:
- Reduce `recovery_timeout` for faster recovery attempts
- Reduce `success_threshold` for easier closure
- Check logs for failures during HALF_OPEN state

```python
# Before: Too strict
breaker = CircuitBreaker(
    recovery_timeout=300.0,    # 5 minutes
    success_threshold=10,      # Need 10 successes
)

# After: More reasonable
breaker = CircuitBreaker(
    recovery_timeout=60.0,     # 1 minute
    success_threshold=2,       # Just 2 successes
)
```

### High Rejection Rate

**Problem**: Many requests rejected by circuit breaker

**Solutions**:
- This is expected behavior when service is down
- Implement fallback strategies
- Monitor upstream service health
- Consider increasing `half_open_max_calls` for faster recovery testing

## Production Examples

The following examples demonstrate real-world usage patterns for the Circuit Breaker implementation in production environments.

### Example 1: Protecting External API Calls

Protect external payment service calls with automatic fallback strategies.

```python
import httpx
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError

# Create a circuit breaker for an external payment service
payment_breaker = CircuitBreaker(
    name="payment_service",
    failure_threshold=5,  # Open after 5 consecutive failures
    recovery_timeout=60.0,  # Try recovery after 60 seconds
    success_threshold=2,  # Close after 2 successes in half-open
    half_open_max_calls=3,  # Allow 3 concurrent calls in half-open
    expected_exception=httpx.HTTPError,  # Only HTTP errors trigger circuit
)


@payment_breaker.protected
async def process_payment(
    amount: float,
    currency: str,
    customer_id: str,
) -> dict[str, Any]:
    """Process payment through external service.

    The circuit breaker will protect against repeated failures
    and provide fast failure when the service is unavailable.

    Args:
        amount: Payment amount
        currency: Currency code (e.g., "USD")
        customer_id: Customer identifier

    Returns:
        Payment confirmation with transaction ID

    Raises:
        CircuitOpenError: If circuit breaker is open
        httpx.HTTPError: If payment service returns error
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.payment-provider.com/v1/charge",
            json={
                "amount": amount,
                "currency": currency,
                "customer_id": customer_id,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


async def process_payment_with_fallback(
    amount: float,
    currency: str,
    customer_id: str,
) -> dict[str, Any]:
    """Process payment with fallback strategy when circuit is open.

    This demonstrates a complete error handling strategy including
    fallback logic when the primary service is unavailable.

    Args:
        amount: Payment amount
        currency: Currency code
        customer_id: Customer identifier

    Returns:
        Payment result or fallback response
    """
    try:
        # Attempt primary payment service
        result = await process_payment(amount, currency, customer_id)
        return result

    except CircuitOpenError:
        # Circuit is open, use fallback strategy
        logger.warning(
            "Payment service circuit breaker is open, using fallback",
            extra={
                "amount": amount,
                "currency": currency,
                "customer_id": customer_id,
            },
        )

        # Option 1: Queue for later processing
        # await queue_payment_for_retry(amount, currency, customer_id)

        # Option 2: Use backup payment processor
        # return await backup_payment_processor.charge(amount, currency, customer_id)

        # Option 3: Return pending status
        return {
            "status": "pending",
            "message": "Payment queued for processing",
            "customer_id": customer_id,
        }

    except httpx.HTTPError as e:
        # Service error that triggered circuit
        logger.error(
            f"Payment service error: {e}",
            extra={
                "amount": amount,
                "currency": currency,
                "customer_id": customer_id,
            },
        )
        raise
```

### Example 2: Database Connection Protection

Protect database operations against connection failures or timeouts.

```python
import asyncio
from example_service.infra.resilience import CircuitBreaker

db_breaker = CircuitBreaker(
    name="database",
    failure_threshold=3,
    recovery_timeout=30.0,
    success_threshold=2,
)


async def fetch_user_data(user_id: int) -> dict[str, Any]:
    """Fetch user data with circuit breaker protection.

    This example shows how to protect database calls that might fail
    due to connection issues or timeouts.
    """
    async with db_breaker:
        # Simulated database call
        # In real implementation, this would use SQLAlchemy or similar
        await asyncio.sleep(0.1)
        return {"user_id": user_id, "name": "John Doe"}
```

### Example 3: Multiple Circuit Breakers in Service

Use separate circuit breakers for different operations of the same service.

```python
import httpx
from example_service.infra.resilience import CircuitBreaker


class ResilientExternalServiceClient:
    """Example client with multiple circuit breakers for different operations.

    This demonstrates how to use separate circuit breakers for different
    endpoints or operations of the same service, allowing fine-grained
    control over resilience behavior.
    """

    def __init__(self, base_url: str) -> None:
        """Initialize client with separate circuit breakers.

        Args:
            base_url: Base URL for the external service
        """
        self.base_url = base_url

        # Separate circuit breakers for different operation types
        self.read_breaker = CircuitBreaker(
            name="service_read",
            failure_threshold=10,  # More tolerant for reads
            recovery_timeout=30.0,
        )

        self.write_breaker = CircuitBreaker(
            name="service_write",
            failure_threshold=3,  # Less tolerant for writes
            recovery_timeout=60.0,
        )

        self.critical_breaker = CircuitBreaker(
            name="service_critical",
            failure_threshold=2,  # Very strict for critical ops
            recovery_timeout=120.0,
        )

    async def read_data(self, resource_id: str) -> dict[str, Any]:
        """Read data with read-specific circuit breaker."""

        @self.read_breaker.protected
        async def _fetch() -> dict[str, Any]:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/data/{resource_id}")
                response.raise_for_status()
                return response.json()

        return await _fetch()

    async def write_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Write data with write-specific circuit breaker."""

        @self.write_breaker.protected
        async def _write() -> dict[str, Any]:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.base_url}/data", json=data)
                response.raise_for_status()
                return response.json()

        return await _write()

    async def critical_operation(self, operation: str) -> dict[str, Any]:
        """Execute critical operation with strictest circuit breaker."""

        @self.critical_breaker.protected
        async def _execute() -> dict[str, Any]:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/critical/{operation}",
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()

        return await _execute()

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all circuit breakers.

        Returns:
            Dictionary with status of all circuit breakers
        """
        return {
            "read": self.read_breaker.get_metrics(),
            "write": self.write_breaker.get_metrics(),
            "critical": self.critical_breaker.get_metrics(),
        }
```

### Example 4: Monitoring and Metrics

Monitor circuit breaker health and send alerts when needed.

```python
import logging
from typing import Callable
from example_service.infra.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


async def monitor_circuit_breaker_health(
    breaker: CircuitBreaker,
    alert_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Monitor circuit breaker and send alerts when needed.

    This example shows how to monitor circuit breaker metrics
    and trigger alerts based on failure rates or state changes.

    Args:
        breaker: Circuit breaker to monitor
        alert_callback: Optional callback for alerts
    """
    metrics = breaker.get_metrics()

    # Check for high failure rate
    if metrics["failure_rate"] > 0.5:
        logger.warning(
            f"High failure rate detected in circuit breaker '{breaker.name}'",
            extra={
                "circuit_breaker": breaker.name,
                "failure_rate": metrics["failure_rate"],
                "state": metrics["state"],
            },
        )

        if alert_callback:
            alert_callback(
                {
                    "type": "high_failure_rate",
                    "breaker": breaker.name,
                    "metrics": metrics,
                }
            )

    # Check if circuit is open
    if metrics["state"] == "open":
        logger.error(
            f"Circuit breaker '{breaker.name}' is OPEN",
            extra={
                "circuit_breaker": breaker.name,
                "total_failures": metrics["total_failures"],
                "total_rejections": metrics["total_rejections"],
                "last_failure": metrics["last_failure_time"],
            },
        )

        if alert_callback:
            alert_callback(
                {
                    "type": "circuit_open",
                    "breaker": breaker.name,
                    "metrics": metrics,
                }
            )
```

### Example 5: Testing with Circuit Breaker

Demonstrate proper testing patterns for circuit breaker behavior.

```python
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError


async def example_test_with_circuit_breaker() -> None:
    """Example showing how to test code with circuit breaker.

    This demonstrates proper testing patterns including:
    - Resetting circuit breaker state between tests
    - Forcing specific states for testing
    - Verifying circuit breaker behavior
    """
    # Create circuit breaker for testing
    test_breaker = CircuitBreaker(
        name="test_service",
        failure_threshold=3,
        recovery_timeout=1.0,
    )

    # Test success case
    @test_breaker.protected
    async def successful_operation() -> str:
        return "success"

    result = await successful_operation()
    assert result == "success"

    # Test failure case
    @test_breaker.protected
    async def failing_operation() -> None:
        raise ValueError("Simulated failure")

    # Trigger failures to open circuit
    for _ in range(3):
        try:
            await failing_operation()
        except ValueError:
            pass

    # Verify circuit is now open
    assert test_breaker.is_open

    # Reset for next test
    await test_breaker.reset()
    assert test_breaker.is_closed
```

### Example 6: Custom Exception Filtering

Use selective exception filtering to only trigger circuit on specific errors.

```python
import httpx
from example_service.infra.resilience import CircuitBreaker


class TransientError(Exception):
    """Transient error that should trigger circuit breaker."""


class PermanentError(Exception):
    """Permanent error that should not trigger circuit breaker."""


# Only transient errors trigger the circuit
selective_breaker = CircuitBreaker(
    name="selective_service",
    failure_threshold=5,
    recovery_timeout=30.0,
    expected_exception=TransientError,  # Only these trigger circuit
)


@selective_breaker.protected
async def smart_api_call(endpoint: str) -> dict[str, Any]:
    """API call with selective error handling.

    TransientError (network issues, timeouts) will trigger the circuit.
    PermanentError (validation, authentication) will pass through.
    """
    try:
        # Simulated API call
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.example.com/{endpoint}")

            if response.status_code == 503:
                # Service unavailable - transient error
                raise TransientError("Service temporarily unavailable")

            if response.status_code == 401:
                # Authentication error - permanent error
                raise PermanentError("Invalid credentials")

            response.raise_for_status()
            return response.json()

    except httpx.TimeoutException as e:
        # Network timeout - transient error
        raise TransientError("Request timeout") from e

    except httpx.ConnectError as e:
        # Connection error - transient error
        raise TransientError("Connection failed") from e
```

### Example 7: Integration with FastAPI Dependency Injection

Use circuit breakers with FastAPI's dependency injection system.

```python
from fastapi import Depends
from example_service.infra.resilience import CircuitBreaker, CircuitOpenError


async def get_payment_breaker() -> CircuitBreaker:
    """FastAPI dependency that provides payment circuit breaker.

    Usage in FastAPI route:
        @app.post("/payments")
        async def create_payment(
            breaker: CircuitBreaker = Depends(get_payment_breaker)
        ):
            async with breaker:
                return await payment_service.charge()
    """
    return payment_breaker


async def example_fastapi_usage() -> dict[str, Any]:
    """Example of using circuit breaker in FastAPI endpoint."""
    breaker = await get_payment_breaker()

    try:
        async with breaker:
            # Payment processing logic
            result = await process_payment(100.0, "USD", "customer_123")
            return result

    except CircuitOpenError:
        # Circuit is open, return service unavailable
        return {
            "error": "Payment service temporarily unavailable",
            "status": "retry_later",
        }
```

## References

- [Martin Fowler - Circuit Breaker](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Microsoft - Circuit Breaker Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
- [Release It! - Michael Nygard](https://pragprog.com/titles/mnee2/release-it-second-edition/)
- [accent-ai Circuit Breaker Implementation](https://github.com/Acliad/accent-ai/blob/main/library/accent-library/accent_library/messaging/circuit_breaker.py)

## License

This implementation is part of the fastapi-template project and follows the same license terms.

## Support

For issues, questions, or contributions:
- File an issue in the repository
- Check existing documentation and examples
- Review test suite for usage patterns
