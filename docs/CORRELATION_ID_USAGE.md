# Correlation ID Usage Guide

This guide explains how to effectively use correlation IDs for distributed tracing in microservices architectures.

## Overview

**Correlation IDs** enable end-to-end tracing of business transactions across multiple services. When properly implemented, they allow you to:

- Track a user's request across all backend services
- Debug issues that span multiple microservices
- Analyze performance bottlenecks in distributed flows
- Correlate logs, metrics, and traces across services

## Quick Start

### 1. Automatic Correlation ID Handling

The `CorrelationIDMiddleware` is **always enabled** and handles correlation IDs automatically:

```python
# No configuration needed - it just works!

# When a request arrives:
# - If X-Correlation-ID header is present → use it
# - If X-Correlation-ID header is missing → generate new UUID

# When sending response:
# - X-Correlation-ID header is automatically added to the response
```

### 2. Accessing Correlation ID in Your Code

Get the correlation ID from the request:

```python
from fastapi import Request
from example_service.app.middleware.correlation_id import get_correlation_id_from_request

@app.get("/api/v1/orders")
async def create_order(request: Request):
    # Option 1: Using helper function (recommended)
    correlation_id = get_correlation_id_from_request(request)

    # Option 2: Direct access from request.state
    correlation_id = request.state.correlation_id

    print(f"Processing order with correlation_id: {correlation_id}")

    # Use correlation_id when calling downstream services
    await call_inventory_service(correlation_id)
    await call_payment_service(correlation_id)

    return {"order_id": "12345", "correlation_id": correlation_id}
```

### 3. Propagating Correlation ID to Downstream Services

**Always pass the correlation ID** when calling other services:

```python
import httpx
from fastapi import Request

async def call_inventory_service(request: Request, product_id: str):
    """Call inventory service with correlation ID propagation."""
    correlation_id = get_correlation_id_from_request(request)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://inventory-service/api/v1/check",
            json={"product_id": product_id},
            headers={
                "X-Correlation-ID": correlation_id  # ← Propagate the ID
            }
        )
        return response.json()
```

## Common Patterns

### Pattern 1: Service Chain with Correlation ID

```python
# Service A (Order Service) - Entry point
@app.post("/api/v1/orders")
async def create_order(request: Request, order_data: dict):
    """Creates order and calls downstream services."""
    correlation_id = get_correlation_id_from_request(request)

    logger.info(
        "Creating order",
        extra={"correlation_id": correlation_id}  # Already in context
    )

    # Call inventory service
    inventory_result = await check_inventory(
        request, order_data["product_id"]
    )

    # Call payment service
    payment_result = await process_payment(
        request, order_data["amount"]
    )

    # Call notification service
    await send_notification(
        request, order_data["customer_email"]
    )

    return {"order_id": "12345", "status": "confirmed"}


async def check_inventory(request: Request, product_id: str):
    """Calls inventory service."""
    correlation_id = get_correlation_id_from_request(request)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://inventory-service/api/v1/check",
            json={"product_id": product_id},
            headers={"X-Correlation-ID": correlation_id}
        )
        return response.json()


# Service B (Inventory Service)
@app.post("/api/v1/check")
async def check_inventory(request: Request, data: dict):
    """Receives correlation ID from Order Service."""
    correlation_id = get_correlation_id_from_request(request)

    # The middleware automatically extracted the correlation ID
    logger.info(
        "Checking inventory",
        extra={"correlation_id": correlation_id, "product_id": data["product_id"]}
    )

    # If this service needs to call another service, pass correlation_id
    await reserve_stock(request, data["product_id"])

    return {"available": True}


# Service C (Warehouse Service)
@app.post("/api/v1/reserve")
async def reserve_stock(request: Request, data: dict):
    """Receives same correlation ID from Inventory Service."""
    correlation_id = get_correlation_id_from_request(request)

    # All three services now share the same correlation_id
    logger.info(
        "Reserving stock",
        extra={"correlation_id": correlation_id}
    )

    return {"reserved": True}
```

**Log Output** (all services):
```json
// Service A (Order Service)
{"correlation_id": "abc123", "request_id": "req-001", "message": "Creating order"}

// Service B (Inventory Service)
{"correlation_id": "abc123", "request_id": "req-002", "message": "Checking inventory"}

// Service C (Warehouse Service)
{"correlation_id": "abc123", "request_id": "req-003", "message": "Reserving stock"}
```

Now you can query logs with `correlation_id=abc123` to see the complete transaction flow!

### Pattern 2: Using HTTP Client with Correlation ID

Create a reusable HTTP client that automatically adds correlation IDs:

```python
from fastapi import Request
import httpx

class ServiceClient:
    """Base HTTP client with automatic correlation ID propagation."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    async def _make_request(
        self,
        request: Request,
        method: str,
        path: str,
        **kwargs
    ):
        """Make HTTP request with correlation ID."""
        correlation_id = get_correlation_id_from_request(request)

        # Add correlation ID to headers
        headers = kwargs.pop("headers", {})
        headers["X-Correlation-ID"] = correlation_id

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs
            )
            response.raise_for_status()
            return response.json()

    async def post(self, request: Request, path: str, **kwargs):
        """POST request with correlation ID."""
        return await self._make_request(request, "POST", path, **kwargs)

    async def get(self, request: Request, path: str, **kwargs):
        """GET request with correlation ID."""
        return await self._make_request(request, "GET", path, **kwargs)


# Usage
inventory_client = ServiceClient("https://inventory-service")
payment_client = ServiceClient("https://payment-service")

@app.post("/api/v1/orders")
async def create_order(request: Request, order_data: dict):
    # Correlation ID is automatically propagated
    inventory = await inventory_client.post(
        request,
        "/api/v1/check",
        json={"product_id": order_data["product_id"]}
    )

    payment = await payment_client.post(
        request,
        "/api/v1/charge",
        json={"amount": order_data["amount"]}
    )

    return {"order_id": "12345"}
```

### Pattern 3: Background Tasks with Correlation ID

When spawning background tasks, preserve the correlation ID:

```python
from fastapi import BackgroundTasks, Request
from example_service.app.middleware.correlation_id import get_correlation_id_from_request

async def send_email_task(correlation_id: str, email: str, subject: str):
    """Background task that uses correlation ID for logging."""
    logger.info(
        "Sending email",
        extra={"correlation_id": correlation_id, "email": email}
    )
    # Send email logic here
    await email_service.send(email, subject)


@app.post("/api/v1/orders")
async def create_order(
    request: Request,
    background_tasks: BackgroundTasks,
    order_data: dict
):
    """Creates order and sends confirmation email in background."""
    correlation_id = get_correlation_id_from_request(request)

    # Save order
    order_id = await save_order(order_data)

    # Schedule background task with correlation ID
    background_tasks.add_task(
        send_email_task,
        correlation_id,  # Pass correlation_id to background task
        order_data["customer_email"],
        f"Order {order_id} confirmed"
    )

    return {"order_id": order_id}
```

### Pattern 4: Message Queue Integration

Propagate correlation IDs through message brokers:

```python
import asyncio
from fastapi import Request
import aio_pika

async def publish_order_event(request: Request, order_data: dict):
    """Publish order event to RabbitMQ with correlation ID."""
    correlation_id = get_correlation_id_from_request(request)

    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
    async with connection:
        channel = await connection.channel()

        # Include correlation_id in message properties
        message = aio_pika.Message(
            body=json.dumps(order_data).encode(),
            correlation_id=correlation_id,  # ← RabbitMQ supports this natively!
            headers={
                "x-correlation-id": correlation_id  # Also in headers for redundancy
            }
        )

        await channel.default_exchange.publish(
            message,
            routing_key="order.created"
        )

        logger.info(
            "Published order event",
            extra={"correlation_id": correlation_id}
        )


# Consumer side
async def consume_order_events():
    """Consume order events and extract correlation ID."""
    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue("order_processor")

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    # Extract correlation_id from message properties
                    correlation_id = message.correlation_id or message.headers.get("x-correlation-id")

                    order_data = json.loads(message.body)

                    logger.info(
                        "Processing order event",
                        extra={"correlation_id": correlation_id, "order_id": order_data["id"]}
                    )

                    # Process order with correlation context
                    await process_order(order_data, correlation_id)
```

## Debugging with Correlation IDs

### Query Logs by Correlation ID

Once you have a correlation ID, you can trace the entire request flow:

```bash
# Loki query
{job="example-service"} | json | correlation_id="abc123"

# Elasticsearch query
GET /logs/_search
{
  "query": {
    "match": {
      "correlation_id": "abc123"
    }
  },
  "sort": [
    { "timestamp": "asc" }
  ]
}

# CloudWatch Logs Insights
fields @timestamp, @message, correlation_id, request_id, service
| filter correlation_id = "abc123"
| sort @timestamp asc
```

### Example Log Output

```json
[
  {
    "timestamp": "2025-11-25T10:00:00.123Z",
    "level": "INFO",
    "service": "order-service",
    "correlation_id": "abc123",
    "request_id": "req-001",
    "message": "Creating order",
    "order_id": "12345"
  },
  {
    "timestamp": "2025-11-25T10:00:00.456Z",
    "level": "INFO",
    "service": "inventory-service",
    "correlation_id": "abc123",
    "request_id": "req-002",
    "message": "Checking inventory",
    "product_id": "PROD-789"
  },
  {
    "timestamp": "2025-11-25T10:00:00.789Z",
    "level": "INFO",
    "service": "warehouse-service",
    "correlation_id": "abc123",
    "request_id": "req-003",
    "message": "Reserving stock",
    "warehouse_id": "WH-01"
  },
  {
    "timestamp": "2025-11-25T10:00:01.012Z",
    "level": "INFO",
    "service": "payment-service",
    "correlation_id": "abc123",
    "request_id": "req-004",
    "message": "Processing payment",
    "amount": 99.99
  }
]
```

All services in the transaction share `correlation_id=abc123`!

## Best Practices

### DO ✅

1. **Always propagate correlation IDs** when calling downstream services
   ```python
   headers = {"X-Correlation-ID": get_correlation_id_from_request(request)}
   ```

2. **Include correlation_id in all structured logs**
   ```python
   logger.info("Processing request", extra={"correlation_id": correlation_id})
   ```

3. **Use correlation IDs in error responses**
   ```python
   raise HTTPException(
       status_code=500,
       detail=f"Error processing request. Correlation ID: {correlation_id}"
   )
   ```

4. **Validate correlation ID format** (optional, for strict environments)
   ```python
   import re
   UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

   if not UUID_PATTERN.match(correlation_id):
       # Regenerate or warn
       pass
   ```

5. **Return correlation ID in API responses** (already automatic via middleware)

### DON'T ❌

1. **Don't generate new correlation IDs** when one already exists
   ```python
   # ❌ BAD: Regenerating breaks the trace
   correlation_id = str(uuid.uuid4())

   # ✅ GOOD: Use existing correlation ID
   correlation_id = get_correlation_id_from_request(request)
   ```

2. **Don't use correlation ID as a request ID**
   ```python
   # ❌ BAD: Confusing different concepts
   request_id = correlation_id

   # ✅ GOOD: Use separate IDs for different purposes
   correlation_id = get_correlation_id_from_request(request)  # Transaction-level
   request_id = request.state.request_id  # Request-level
   ```

3. **Don't forget to propagate in async tasks**
   ```python
   # ❌ BAD: Losing correlation context
   background_tasks.add_task(send_email, email)

   # ✅ GOOD: Pass correlation_id to background task
   correlation_id = get_correlation_id_from_request(request)
   background_tasks.add_task(send_email, email, correlation_id)
   ```

4. **Don't use correlation IDs for authorization**
   ```python
   # ❌ BAD: Correlation IDs are not secrets
   if correlation_id == "secret-value":
       allow_access()

   # ✅ GOOD: Use proper authentication
   if user.has_permission("admin"):
       allow_access()
   ```

## Troubleshooting

### Issue: Correlation ID Not Appearing in Logs

**Problem**: Logs don't show `correlation_id` field

**Solution**: Ensure you're using structured logging with `extra` parameter:

```python
# ❌ Wrong
logger.info(f"Processing order {correlation_id}")

# ✅ Correct
logger.info("Processing order", extra={"correlation_id": correlation_id})
```

### Issue: Different Correlation IDs in Service Chain

**Problem**: Each service has a different correlation ID for the same transaction

**Solution**: Ensure correlation ID is propagated in HTTP headers:

```python
# Check that you're passing the header
async with httpx.AsyncClient() as client:
    response = await client.post(
        url,
        headers={"X-Correlation-ID": correlation_id}  # ← Must include this
    )
```

### Issue: Lost Correlation ID in Background Tasks

**Problem**: Background tasks don't have correlation ID in logs

**Solution**: Explicitly pass correlation ID to background task:

```python
# Extract correlation_id before scheduling background task
correlation_id = get_correlation_id_from_request(request)

# Pass it as a parameter
background_tasks.add_task(my_task, correlation_id, other_params)
```

## Related Documentation

- [Middleware Architecture](./MIDDLEWARE_ARCHITECTURE.md) - Overall middleware design
- [Monitoring Setup](./MONITORING_SETUP.md) - Querying logs by correlation ID
- [Deployment Validation](./DEPLOYMENT_VALIDATION.md) - Testing correlation ID propagation

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-25 | AI Assistant | Initial correlation ID usage guide |
