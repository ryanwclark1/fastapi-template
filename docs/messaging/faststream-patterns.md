# FastStream Messaging Patterns Guide

This guide documents all FastStream messaging patterns and best practices used in `example_service`. These patterns serve as a template for migrating services from `aio-pika` to FastStream.

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Exchange and Queue Management](#exchange-and-queue-management)
- [Dead Letter Queue (DLQ)](#dead-letter-queue-dlq)
- [Retry Patterns](#retry-patterns)
- [Health Checks](#health-checks)
- [Examples](#examples)
- [Migration Guide](#migration-guide)

## Overview

FastStream is an open-source framework for building asynchronous web services that interact with event streams. In `example_service`, we use FastStream with RabbitMQ for:

- Event-driven communication between services
- Background task processing
- AsyncAPI documentation generation
- Distributed tracing integration

### Key Features

- **Automatic Connection Management**: FastStream handles broker lifecycle automatically
- **AsyncAPI Documentation**: Automatic generation at `/asyncapi`
- **Type Safety**: Pydantic models for event schemas
- **DLQ Support**: Built-in dead letter queue configuration
- **Retry Integration**: Works with existing `utils.retry` decorator
- **Health Monitoring**: Connection state tracking and health checks

## Core Concepts

### Broker and Router

The `RabbitRouter` wraps `RabbitBroker` and provides FastAPI integration:

```python
from example_service.infra.messaging.broker import get_broker, get_router

# In FastAPI endpoints
@router.post("/publish")
async def publish_event(
    broker: RabbitBroker = Depends(get_broker)
):
    await broker.publish(message={"event": "user.created"}, queue="user-events")
```

### Subscribers

Use `@router.subscriber()` decorator to consume messages:

```python
from example_service.infra.messaging.broker import router
from example_service.infra.messaging.exchanges import EXAMPLE_EVENTS_QUEUE, DOMAIN_EVENTS_EXCHANGE

@router.subscriber(
    EXAMPLE_EVENTS_QUEUE,
    exchange=DOMAIN_EVENTS_EXCHANGE,
)
async def handle_example_created(event: ExampleCreatedEvent) -> None:
    # Process event
    # FastStream automatically deserializes to ExampleCreatedEvent based on message content
    pass
```

**Note**: Routing keys are specified in the `RabbitQueue` definition, not as a parameter to `@router.subscriber()`. If you need routing key filtering, create separate queues with routing keys in their definitions (see `examples/exchange_patterns.py`).

## Exchange and Queue Management

### Explicit Exchange Configuration

Always use explicit `RabbitExchange` objects instead of implicit exchanges:

```python
from faststream.rabbit import ExchangeType, RabbitExchange

DOMAIN_EVENTS_EXCHANGE = RabbitExchange(
    name="example-service",
    type=ExchangeType.TOPIC,
    durable=True,
    auto_delete=False,
)
```

### Queue Definitions with DLQ

Configure queues with DLQ arguments:

```python
from example_service.infra.messaging.exchanges import create_queue_with_dlq

EXAMPLE_EVENTS_QUEUE = create_queue_with_dlq(
    queue_name="example-events",
    dlq_routing_key="dlq.example-events",
)
```

### Routing Keys

Use routing key helpers for consistent naming:

```python
from example_service.infra.messaging.conventions import (
    get_routing_key,
    get_routing_key_pattern,
)

# Exact match
routing_key = get_routing_key("example.created")

# Pattern match
pattern = get_routing_key_pattern("example")  # "example.*"

# Tenant-specific
tenant_pattern = get_tenant_routing_key_pattern("example", "tenant-123")
```

### Exchange Types

- **Topic**: Flexible routing with patterns (`example.*`, `example.#`)
- **Direct**: Exact routing key match
- **Fanout**: Broadcast to all bound queues (routing key ignored)

See `examples/exchange_patterns.py` for comprehensive examples.

## Dead Letter Queue (DLQ)

### Configuration

DLQ is configured via queue arguments:

```python
RabbitQueue(
    name="example-events",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "example-service.dlq",
        "x-dead-letter-routing-key": "dlq.example-events",
    },
)
```

### DLQ Handler

Process DLQ messages for monitoring and alerting:

```python
from example_service.infra.messaging.exchanges import DLQ_QUEUE, DLQ_EXCHANGE

@router.subscriber(DLQ_QUEUE, exchange=DLQ_EXCHANGE)
async def handle_dlq_message(message: dict) -> None:
    # Extract metadata
    headers = message.get("headers", {})
    original_queue = headers.get("x-original-queue")
    retry_count = headers.get("x-retry-count", 0)

    # Log, alert, or replay
    logger.error(f"DLQ message from {original_queue} after {retry_count} retries")
```

### DLQ Utilities

Use utilities from `examples/dlq_patterns.py`:

- `extract_dlq_metadata()`: Extract failure information
- `replay_dlq_message()`: Replay failed messages
- `should_replay_message()`: Determine replay eligibility
- `DLQMonitor`: Monitor DLQ conditions

## Retry Patterns

### Using utils.retry Decorator

The existing `utils.retry` decorator works seamlessly with FastStream handlers:

```python
from example_service.utils.retry import retry

@router.subscriber(EXAMPLE_EVENTS_QUEUE)
@retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
async def handle_event(event: ExampleCreatedEvent) -> None:
    # Handler logic
    pass
```

**Note**: The retry decorator includes:
- Exponential backoff with jitter (prevents thundering herd) - enabled by default
- Exception-based retry decisions (via `exceptions` tuple or `retry_if` function)
- Time-based retry limits (via `stop_after_delay` parameter)
- Retry statistics and metrics (available via `RetryError.statistics`)
- Integration with Prometheus metrics (automatic tracking)

### Exception-Based Retry

Only retry transient errors:

```python
@retry(
    max_attempts=5,
    exceptions=(ConnectionError, TimeoutError, OSError),
)
async def handle_event(event: ExampleCreatedEvent) -> None:
    # Only ConnectionError, TimeoutError, OSError trigger retries
    pass
```

### Retry Callbacks

Monitor retry attempts:

```python
def on_retry(exception: Exception, attempt: int) -> None:
    logger.warning(f"Retry attempt {attempt}: {exception}")

@retry(max_attempts=3, on_retry=on_retry)
async def handle_event(event: ExampleCreatedEvent) -> None:
    pass
```

### When to Retry vs DLQ

**Use Retry For:**
- Transient errors (network issues, timeouts)
- Errors that may resolve with time
- Idempotent operations

**Go to DLQ For:**
- Permanent errors (validation failures)
- Errors that won't resolve with retry
- Non-idempotent operations

See `examples/retry_patterns.py` for comprehensive examples.

## Health Checks

### Broker Health Check

Use `check_broker_health()` to check broker status:

```python
from example_service.infra.messaging.broker import check_broker_health

health = await check_broker_health()
# Returns: {
#     "status": "healthy",
#     "state": "connected",
#     "is_connected": True,
# }
```

### Connection States

- `DISCONNECTED`: Broker not connected
- `CONNECTING`: Connection in progress
- `CONNECTED`: Connected and operational
- `RECONNECTING`: Reconnecting after loss
- `FAILED`: Connection failed

### Health Provider Integration

The `RabbitMQHealthProvider` automatically uses `check_broker_health()`:

```python
from example_service.features.health.providers import RabbitMQHealthProvider

provider = RabbitMQHealthProvider()
aggregator.add_provider(provider)
```

## Examples

### Basic Handler

```python
from example_service.infra.messaging.broker import router
from example_service.infra.messaging.exchanges import (
    DOMAIN_EVENTS_EXCHANGE,
    EXAMPLE_EVENTS_QUEUE,
)
from example_service.utils.retry import retry

@router.subscriber(
    EXAMPLE_EVENTS_QUEUE,
    exchange=DOMAIN_EVENTS_EXCHANGE,
)
@retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
async def handle_example_created(event: ExampleCreatedEvent) -> None:
    logger.info(f"Processing event: {event.event_id}")
    # Business logic
    # FastStream automatically deserializes messages to ExampleCreatedEvent
    pass
```

### Publishing Messages

```python
from example_service.infra.messaging.broker import get_broker

@router.post("/publish")
async def publish_event(
    broker: RabbitBroker = Depends(get_broker)
):
    event = ExampleCreatedEvent(data={"id": "123"})
    await broker.publish(
        message=event.model_dump(),
        queue="example-events",
        routing_key="example.created",
    )
```

### Request/Response Pattern

```python
@router.subscriber(REQUEST_QUEUE)
@router.publisher(RESPONSE_QUEUE)
async def handle_request(message: dict) -> dict:
    # Process request
    result = process(message)
    # Return value is auto-published to RESPONSE_QUEUE
    return {"result": result}
```

## Migration Guide

### From aio-pika to FastStream

1. **Replace Connection Management**:
   - Old: Manual `connect()`/`disconnect()`
   - New: Automatic via `RabbitRouter`

2. **Replace Subscriptions**:
   - Old: `subscribe(queue, callback)`
   - New: `@router.subscriber(queue)`

3. **Replace Publishing**:
   - Old: `publish(exchange, routing_key, message)`
   - New: `broker.publish(message, queue=..., routing_key=...)`

4. **Replace Exchange/Queue Creation**:
   - Old: Manual `create_exchange()`/`create_queue()`
   - New: Declared in `RabbitExchange`/`RabbitQueue`

5. **Update Health Checks**:
   - Old: Custom `ping()` method
   - New: `check_broker_health()`

6. **Update Retry Logic**:
   - Old: Custom `with_retry()` decorator
   - New: Use `utils.retry` decorator

### Checklist

- [ ] Replace `aio-pika` imports with FastStream
- [ ] Convert handlers to `@router.subscriber()` decorators
- [ ] Update exchange/queue definitions to use `RabbitExchange`/`RabbitQueue`
- [ ] Configure DLQ arguments on all production queues
- [ ] Add retry decorators to handlers
- [ ] Update health checks to use `check_broker_health()`
- [ ] Test AsyncAPI documentation at `/asyncapi`
- [ ] Verify DLQ routing works correctly
- [ ] Update tests to use new patterns

## Security Considerations

### Format String Injection Prevention

When using routing keys with format strings, be aware of format string injection risks:

**Vulnerable Pattern** (DO NOT USE):
```python
# Dangerous: All keys from payload are passed to format()
routing_key = fmt.format(**event.content)  # Injection risk!
```

**Secure Pattern** (RECOMMENDED):
```python
# Safe: Extract only required keys from format string
required_keys = extract_format_keys(fmt)  # Parse format string
safe_vars = {k: event.content[k] for k in required_keys if k in event.content}
routing_key = fmt.format(**safe_vars)  # Only required keys available
```

**Best Practices**:
- Use explicit routing keys when possible (avoid format strings)
- If using format strings, extract and validate field names first
- Block forbidden attributes (__class__, __dict__, etc.)
- Validate routing key length (max 255 chars per AMQP spec)
- Escape special characters in routing key values

See `accent-bus` EventMiddleware for a comprehensive security implementation.

### Access Control

Consider adding access control headers to messages:
- `required_access`: Permission string (e.g., "event.UserCreated")
- `origin_uuid`: Service identifier for tracking
- `timestamp`: Event timestamp for auditing

## Advanced Patterns

### Event Organization for Large Services

For services with many event types, consider domain-based organization:

```
events/
  user/
    models.py      # UserCreatedEvent, UserUpdatedEvent
    routing.py     # Routing key formats per event
  order/
    models.py
    routing.py
```

This pattern scales better than a flat structure. See `accent-bus` for a complete example.

### Multiple Retry Policies

The current `utils.retry` uses exponential backoff. Advanced use cases may need:
- **IMMEDIATE**: No delay (use with caution)
- **LINEAR**: Fixed delay between attempts
- **EXPONENTIAL**: Exponential backoff (current default)
- **FIBONACCI**: Fibonacci sequence delays

These can be implemented by customizing the retry decorator or using DLQ middleware.

### DLQ Retry Statistics in Headers

For detailed retry analysis, track statistics in message headers:
- Retry attempt count
- Total delay duration
- Exception types encountered
- Start/end timestamps

See `accent-bus` DLQRetryStatistics for a complete implementation.

## Reference

- [FastStream Documentation](https://faststream.ag2.ai/latest/getting-started/)
- [RabbitMQ Best Practices](https://www.rabbitmq.com/best-practices.html)
- [AsyncAPI Specification](https://www.asyncapi.com/)
- [accent-bus Patterns](accent-bus-additional-patterns.md): Advanced patterns from accent-bus

## Related Files

- `example_service/infra/messaging/broker.py`: Broker configuration
- `example_service/infra/messaging/handlers.py`: Event handlers
- `example_service/infra/messaging/exchanges.py`: Exchange/queue definitions
- `example_service/infra/messaging/conventions.py`: Naming conventions
- `example_service/infra/messaging/examples/`: Comprehensive examples
- `docs/messaging/accent-bus-additional-patterns.md`: Advanced patterns reference

