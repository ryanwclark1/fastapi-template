# FastStream Migration Checklist for accent-hub

This document outlines recommendations for improving the `example_service` FastStream implementation before using it as a template for migrating `accent-hub` from aio-pika to FastStream.

## Current State Analysis

### example_service (FastStream-based)
- ✅ Uses FastStream's `RabbitRouter` for FastAPI integration
- ✅ Automatic AsyncAPI documentation at `/asyncapi`
- ✅ OpenTelemetry tracing via `RabbitTelemetryMiddleware`
- ✅ Simple broker setup with `get_broker()` dependency
- ✅ Handler registration via decorators
- ✅ `broker_context()` for Taskiq workers
- ✅ DLQ support with comprehensive examples (`examples/dlq_patterns.py`)
- ✅ Explicit exchange management with routing key patterns
- ✅ Retry patterns using `utils.retry` decorator (`examples/retry_patterns.py`)
- ✅ Health checks with connection state tracking
- ✅ Comprehensive examples and patterns

### accent-hub (aio-pika-based)
- ✅ Custom `MessageBroker` class with manual connection management
- ✅ Explicit exchange and queue setup
- ✅ Dead Letter Queue (DLQ) support
- ✅ Sophisticated retry logic with exponential backoff
- ✅ Health checks and connection monitoring
- ✅ Queue/exchange naming conventions
- ✅ Priority queue support
- ⚠️ More complex, manual infrastructure
- ⚠️ No AsyncAPI documentation
- ⚠️ Manual tracing setup

## Recommended Improvements to example_service

### 1. Dead Letter Queue (DLQ) Support ⚠️ HIGH PRIORITY

**Current State:** DLQ mentioned in docs but not implemented in handlers.

**Recommendation:** Add DLQ configuration examples to handlers.

```python
# In broker.py or handlers.py
from faststream.rabbit import RabbitQueue, RabbitExchange, ExchangeType

DLQ_EXCHANGE = RabbitExchange(
    "example-service.dlq",
    type=ExchangeType.TOPIC,
    durable=True,
)

DLQ_QUEUE = RabbitQueue(
    "example-service.dlq",
    durable=True,
    arguments={
        "x-message-ttl": 86400000,  # 24 hours
    },
)

# In handlers, add DLQ arguments:
@router.subscriber(
    RabbitQueue(
        EXAMPLE_EVENTS_QUEUE,
        durable=True,
        auto_delete=False,
        arguments={
            "x-dead-letter-exchange": "example-service.dlq",
            "x-dead-letter-routing-key": "example-events.dlq",
            "x-max-retries": 3,  # Max retries before DLQ
        },
    )
)
async def handle_example_created(event: ExampleCreatedEvent) -> None:
    ...
```

**Action Items:**
- [x] Add DLQ exchange and queue definitions (in `exchanges.py`)
- [x] Add DLQ arguments to queue configurations (in `exchanges.py`)
- [x] Create DLQ handler example (in `handlers.py` and `examples/dlq_patterns.py`)
- [x] Document DLQ monitoring patterns (in `examples/dlq_patterns.py` and `faststream-patterns.md`)

### 2. Explicit Exchange Management ⚠️ MEDIUM PRIORITY

**Current State:** FastStream handles exchanges implicitly, but accent-hub uses explicit exchanges.

**Recommendation:** Add explicit exchange setup pattern.

```python
# In broker.py
from faststream.rabbit import RabbitExchange, ExchangeType

DOMAIN_EVENTS_EXCHANGE = RabbitExchange(
    rabbit_settings.exchange_name,
    type=ExchangeType.TOPIC,
    durable=True,
)

# In handlers, bind to explicit exchange:
@router.subscriber(
    RabbitQueue(
        EXAMPLE_EVENTS_QUEUE,
        durable=True,
    ),
    exchange=DOMAIN_EVENTS_EXCHANGE,
    routing_key="example.*",
)
async def handle_example_created(event: ExampleCreatedEvent) -> None:
    ...
```

**Action Items:**
- [x] Add exchange definitions module (`exchanges.py`)
- [x] Update handlers to use explicit exchanges (in `handlers.py`)
- [x] Document exchange naming conventions (`conventions.py` and `examples/exchange_patterns.py`)
- [x] Add exchange setup documentation (FastStream handles automatically)

### 3. Retry and Error Handling Patterns ⚠️ MEDIUM PRIORITY

**Current State:** Basic try/except in handlers, no retry decorators.

**Recommendation:** Add retry middleware/decorator pattern.

```python
# In middleware.py or new retry.py
from functools import wraps
from typing import TypeVar, Callable, Any
import asyncio
import logging

F = TypeVar("F", bound=Callable[..., Any])

def with_retry(
    max_retries: int = 3,
    backoff_base: float = 2.0,
    max_delay: float = 60.0,
) -> Callable[[F], F]:
    """Decorator for retry logic with exponential backoff."""
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = min(backoff_base ** attempt, max_delay)
                        logger.warning(
                            f"Handler {func.__name__} failed (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {delay}s",
                            extra={"error": str(e), "attempt": attempt + 1},
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Handler {func.__name__} failed after {max_retries} attempts",
                            extra={"error": str(e)},
                            exc_info=True,
                        )
            raise last_error  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
```

**Action Items:**
- [x] Add retry decorator integration (using existing `utils.retry` in `handlers.py` and `examples/retry_patterns.py`)
- [x] Update handler examples to use retry decorator (all handlers in `handlers.py`)
- [x] Document retry vs DLQ decision criteria (in `examples/retry_patterns.py` and `faststream-patterns.md`)
- [x] Add metrics for retry counts (existing `utils.retry` already has metrics)

### 4. Connection Health Checks ⚠️ LOW PRIORITY

**Current State:** FastStream handles connection internally, no explicit health check.

**Recommendation:** Add health check utility.

```python
# In broker.py
async def check_broker_health() -> dict[str, Any]:
    """Check RabbitMQ broker health.

    Returns:
        Health status dictionary.
    """
    if broker is None:
        return {"status": "unavailable", "reason": "broker_not_configured"}

    try:
        # FastStream broker has connection state
        if hasattr(broker, "connection") and broker.connection:
            if broker.connection.is_closed:
                return {"status": "unhealthy", "reason": "connection_closed"}
            return {"status": "healthy"}
        return {"status": "unknown", "reason": "connection_state_unknown"}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)}
```

**Action Items:**
- [x] Add health check function (`check_broker_health()` in `broker.py`)
- [x] Integrate with health endpoint (updated `RabbitMQHealthProvider` in `features/health/providers.py`)
- [x] Document health check patterns (in `faststream-patterns.md`)

### 5. Queue/Exchange Naming Conventions ⚠️ LOW PRIORITY

**Current State:** Basic queue names, no explicit conventions module.

**Recommendation:** Add naming conventions module (similar to accent-hub's `exchanges.py`).

```python
# In new file: messaging/conventions.py
"""Queue and exchange naming conventions."""

from example_service.core.settings import get_rabbit_settings

rabbit_settings = get_rabbit_settings()

def get_domain_events_exchange() -> str:
    """Get domain events exchange name."""
    return rabbit_settings.exchange_name

def get_dlq_exchange() -> str:
    """Get dead letter queue exchange name."""
    return f"{rabbit_settings.queue_prefix}.dlq"

def get_queue_name(base_name: str) -> str:
    """Get fully qualified queue name with prefix."""
    return rabbit_settings.get_prefixed_queue(base_name)

# Constants
DOMAIN_EVENTS_EXCHANGE = get_domain_events_exchange()
DLQ_EXCHANGE = get_dlq_exchange()
EXAMPLE_EVENTS_QUEUE = get_queue_name("example-events")
```

**Action Items:**
- [x] Create conventions module (`conventions.py`)
- [x] Update handlers to use conventions (handlers use `exchanges.py` which uses conventions)
- [x] Document naming patterns (in `conventions.py` and `faststream-patterns.md`)

### 6. Message Priority Support ⚠️ LOW PRIORITY

**Current State:** Not explicitly shown in examples.

**Recommendation:** Add priority queue example.

```python
# In handlers.py or examples
@router.subscriber(
    RabbitQueue(
        PRIORITY_QUEUE,
        durable=True,
        arguments={
            "x-max-priority": 10,  # Enable priority queue
        },
    )
)
async def handle_priority_event(event: PriorityEvent) -> None:
    ...

# When publishing:
await broker.publish(
    message=event.model_dump(),
    queue=PRIORITY_QUEUE,
    priority=event.priority,  # 0-10
)
```

**Action Items:**
- [ ] Add priority queue example
- [ ] Document priority usage patterns

### 7. Testing Patterns ⚠️ MEDIUM PRIORITY

**Current State:** Basic test examples exist.

**Recommendation:** Add comprehensive test examples for:
- Handler testing with TestRabbitBroker
- DLQ testing
- Retry logic testing
- Connection failure testing

**Action Items:**
- [ ] Add test examples for DLQ
- [ ] Add test examples for retries
- [ ] Add integration test patterns

## Migration Strategy for accent-hub

### Phase 1: Preparation (Do in example_service first) ✅ COMPLETE
1. ✅ Implement DLQ support (`exchanges.py`, `handlers.py`, `examples/dlq_patterns.py`)
2. ✅ Add explicit exchange management (`exchanges.py`, `handlers.py`, `examples/exchange_patterns.py`)
3. ✅ Add retry patterns (`handlers.py`, `examples/retry_patterns.py`)
4. ✅ Add naming conventions module (`conventions.py`)

### Phase 2: accent-hub Migration
1. Replace `MessageBroker` class with FastStream `RabbitRouter`
2. Convert handlers from `subscribe()` callbacks to `@router.subscriber()` decorators
3. Migrate event publishing from `publish_event()` to `broker.publish()`
4. Update connection management to use FastStream's lifecycle
5. Migrate exchange/queue setup to FastStream patterns
6. Update health checks to use FastStream broker state

### Key Differences to Handle

| Feature       | accent-hub (aio-pika)                     | FastStream Pattern                        |
| ------------- | ----------------------------------------- | ----------------------------------------- |
| Connection    | Manual `connect()`/`disconnect()`         | Automatic via `RabbitRouter`              |
| Subscriptions | `subscribe(queue, callback)`              | `@router.subscriber(queue)`               |
| Publishing    | `publish(exchange, routing_key, message)` | `broker.publish(message, queue=...)`      |
| Exchanges     | Manual `create_exchange()`                | Declared in `RabbitExchange`              |
| Queues        | Manual `create_queue()`                   | Declared in `RabbitQueue`                 |
| Health        | Custom `ping()` method                    | Check broker connection state             |
| Retries       | Custom `with_retry()` decorator           | Can reuse pattern or use FastStream retry |

## Documentation Updates Needed

1. **Migration Guide:** Step-by-step guide for converting aio-pika to FastStream
2. **Pattern Examples:** DLQ, retries, exchanges, priority queues
3. **Testing Guide:** How to test FastStream handlers
4. **Troubleshooting:** Common issues and solutions

## Summary

**Must Have Before Migration:**
- ✅ DLQ support (HIGH) - **COMPLETE**
- ✅ Explicit exchange management (MEDIUM) - **COMPLETE**
- ✅ Retry patterns (MEDIUM) - **COMPLETE**

**Nice to Have:**
- Health check utilities
- Naming conventions module
- Priority queue examples
- Enhanced testing patterns

**Estimated Effort:**
- DLQ support: 2-4 hours
- Exchange management: 2-3 hours
- Retry patterns: 2-3 hours
- Documentation: 2-3 hours
- **Total: 8-13 hours**

## Next Steps

1. Review this checklist with the team
2. Prioritize improvements based on accent-hub needs
3. Implement improvements in example_service
4. Test improvements thoroughly
5. Update documentation
6. Begin accent-hub migration

