# Phase 5: Background Tasks - Quick Start Guide

## Overview

Phase 5 adds asynchronous background task processing for notifications, making notification delivery non-blocking and scalable.

## Key Features

✓ **Non-blocking notification creation** - API returns immediately
✓ **Automatic retry with exponential backoff** - Failed deliveries are retried automatically
✓ **Scheduled notifications** - Send notifications at a specific time
✓ **Multi-channel dispatch** - Email, WebSocket, Webhook, In-App
✓ **Comprehensive logging** - Structured logs with context
✓ **Metrics tracking** - Prometheus metrics for monitoring

## Architecture

```
API Request → Create Notification → Queue Background Task → Return Response
                                           ↓
                                    RabbitMQ Queue
                                           ↓
                                    Taskiq Worker
                                           ↓
                             Dispatch to All Channels
```

## Setup

### 1. Start RabbitMQ

```bash
docker run -d --name rabbitmq \
  -p 5672:5672 \
  -p 15672:15672 \
  rabbitmq:3-management
```

### 2. Configure Environment

```bash
# .env
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/

# Optional: Result backend
REDIS_HOST=localhost
REDIS_PORT=6379
TASK_RESULT_BACKEND=redis  # or "postgres"
```

### 3. Start Taskiq Worker

```bash
# Start worker process
taskiq worker example_service.infra.tasks.broker:broker

# Or with auto-reload for development
taskiq worker example_service.infra.tasks.broker:broker --reload
```

### 4. Start FastAPI Application

```bash
# The scheduler runs automatically in the FastAPI process
uvicorn example_service.app.main:app --reload
```

## Usage

### Create Immediate Notification

```python
from example_service.features.notifications.service import get_notification_service

service = get_notification_service()

notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="task_assigned",
    title="New Task Assigned",
    body="You have been assigned a new task",
    priority="high",
    # scheduled_for=None means immediate dispatch via background task
)

await session.commit()
# API returns immediately - dispatch happens in background
```

### Create Scheduled Notification

```python
from datetime import UTC, datetime, timedelta

scheduled_time = datetime.now(UTC) + timedelta(minutes=30)

notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="reminder",
    title="Meeting Reminder",
    body="Team standup in 30 minutes",
    scheduled_for=scheduled_time,  # Will be dispatched at this time
)

await session.commit()
# Will be processed by process_scheduled_notifications task
```

### Manual Retry

```python
from example_service.workers.notifications.tasks import retry_failed_delivery_task

# Retry a failed delivery
task = await retry_failed_delivery_task.kiq(
    delivery_id="<delivery-uuid>",
)

# Optionally wait for result
result = await task.wait_result(timeout=30)
```

## Background Tasks

### 1. dispatch_notification_task

**Triggered**: Automatically when notification created with `scheduled_for=None`

**Purpose**: Dispatch notification to all enabled channels

**Retry**: Auto-retries on failure (max 3 attempts)

```python
# Called automatically by NotificationService.create_notification()
# Or manually:
from example_service.workers.notifications.tasks import dispatch_notification_task

task = await dispatch_notification_task.kiq(
    notification_id="<notification-uuid>",
)
```

### 2. retry_failed_delivery_task

**Triggered**: Manually (or via future retry processor)

**Purpose**: Retry a failed delivery with exponential backoff

**Retry**: Auto-retries on failure (max 3 attempts)

```python
from example_service.workers.notifications.tasks import retry_failed_delivery_task

task = await retry_failed_delivery_task.kiq(
    delivery_id="<delivery-uuid>",
)
```

### 3. process_scheduled_notifications

**Triggered**: Automatically every 1 minute via APScheduler

**Purpose**: Find and dispatch scheduled notifications

**Retry**: No retry (runs every minute anyway)

```python
# Runs automatically - can also trigger manually:
from example_service.workers.notifications.tasks import process_scheduled_notifications

task = await process_scheduled_notifications.kiq()
```

## Monitoring

### Check Notification Status

```python
from example_service.features.notifications.repository import (
    get_notification_repository,
    get_notification_delivery_repository,
)

# Get notification
notification = await notification_repo.get(session, notification_id)
print(f"Status: {notification.status}")
print(f"Dispatched: {notification.dispatched_at}")

# Get deliveries
deliveries = await delivery_repo.list_for_notification(session, notification_id)
for delivery in deliveries:
    print(f"Channel: {delivery.channel} - Status: {delivery.status}")
```

### Query Database

```sql
-- Pending scheduled notifications
SELECT id, user_id, notification_type, scheduled_for, status
FROM notifications
WHERE status = 'pending'
  AND scheduled_for IS NOT NULL
  AND scheduled_for <= NOW()
ORDER BY scheduled_for ASC;

-- Failed deliveries needing retry
SELECT
    nd.id,
    nd.notification_id,
    nd.channel,
    nd.status,
    nd.attempt_count,
    nd.max_attempts,
    nd.next_retry_at,
    nd.error_message
FROM notification_deliveries nd
WHERE nd.status IN ('pending', 'retrying')
  AND nd.attempt_count < nd.max_attempts
  AND (nd.next_retry_at IS NULL OR nd.next_retry_at <= NOW())
ORDER BY nd.next_retry_at ASC;

-- Delivery success rate by channel
SELECT
    channel,
    COUNT(*) as total,
    SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as delivered,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM notification_deliveries
GROUP BY channel;
```

### Prometheus Metrics

Available at `http://localhost:8000/metrics`:

```python
# Notification creation
notification_created_total{notification_type="task_assigned", priority="high"}

# Notification dispatch
notification_dispatched_total{notification_type="task_assigned"}

# Delivery status
notification_delivered_total{channel="email", status="delivered"}

# Retry attempts
notification_retry_total{channel="email"}

# Exhausted retries
notification_retry_exhausted_total{channel="webhook"}
```

### Logs

Structured logs with context:

```json
{
  "level": "info",
  "message": "Notification dispatched successfully",
  "notification_id": "01234567-89ab-cdef-0123-456789abcdef",
  "deliveries_count": 3,
  "channels": ["email", "websocket", "in_app"],
  "timestamp": "2025-12-10T12:34:56.789Z"
}
```

## Retry Strategy

### Exponential Backoff

Failed deliveries are retried with increasing delays:

| Attempt | Delay | Total Elapsed |
|---------|-------|---------------|
| 1 | Immediate | 0 min |
| 2 | 2 minutes | 2 min |
| 3 | 4 minutes | 6 min |
| 4 | 8 minutes | 14 min |
| 5 | 16 minutes | 30 min |

**Max delay**: 1 hour
**Max attempts**: 5 (email/webhook), 1 (websocket/in-app)

### Retry Logic

```python
# Exponential backoff formula
backoff_seconds = min(2 ** attempt_count * 60, 3600)
next_retry_at = now + timedelta(seconds=backoff_seconds)
```

## Troubleshooting

### Notifications not being dispatched

**Check**: Is the Taskiq worker running?

```bash
ps aux | grep taskiq
```

**Check**: Is RabbitMQ running?

```bash
docker ps | grep rabbitmq
```

**Check**: Are tasks being queued?

```bash
# RabbitMQ Management UI
open http://localhost:15672
# Login: guest/guest
# Check Queues tab for "taskiq-tasks" queue
```

### Scheduled notifications not processing

**Check**: Is APScheduler running?

```python
# In FastAPI logs, you should see:
# "APScheduler started with N jobs"
# "Setting up scheduled jobs with APScheduler"
```

**Check**: Is the scheduled job registered?

```bash
curl http://localhost:8000/api/v1/tasks/scheduled | jq
# Should include "process_scheduled_notifications"
```

### Deliveries failing repeatedly

**Check**: Delivery error messages

```sql
SELECT
    channel,
    error_message,
    error_category,
    COUNT(*) as count
FROM notification_deliveries
WHERE status = 'failed'
GROUP BY channel, error_message, error_category
ORDER BY count DESC;
```

**Check**: Channel configuration (email provider, webhook URLs, etc.)

## Best Practices

### 1. Use Scheduled Notifications for Future Delivery

```python
# Good: Scheduled notification
notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="reminder",
    title="Meeting Reminder",
    scheduled_for=meeting_time - timedelta(minutes=5),
)
```

### 2. Set Appropriate Priority

```python
# Critical: urgent
# Important: high
# Normal: normal
# FYI: low

notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="security_alert",
    title="Suspicious Login Detected",
    priority="urgent",  # High priority for security alerts
)
```

### 3. Use Expiration for Time-Sensitive Notifications

```python
from datetime import UTC, datetime, timedelta

notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="flash_sale",
    title="Flash Sale - 2 Hours Only!",
    expires_at=datetime.now(UTC) + timedelta(hours=2),
    auto_dismiss=True,
)
```

### 4. Track Source Entity

```python
notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="comment_reply",
    title="New Reply to Your Comment",
    source_entity_type="comment",
    source_entity_id="comment-456",
    correlation_id=request.headers.get("X-Request-ID"),
)
```

### 5. Handle Errors Gracefully

```python
try:
    notification = await service.create_notification(
        session=session,
        user_id="user-123",
        notification_type="task_assigned",
        title="New Task",
    )
    await session.commit()
except Exception as exc:
    logger.exception("Failed to create notification", extra={"user_id": "user-123"})
    # Application continues - notification failure shouldn't break main flow
```

## Performance Tips

### 1. Batch Operations

```python
# Create multiple notifications in one transaction
async with session.begin():
    for user_id in user_ids:
        await service.create_notification(
            session=session,
            user_id=user_id,
            notification_type="announcement",
            title="System Announcement",
        )
# All queued for background dispatch
```

### 2. Use Templates for Consistency

```python
# Create reusable templates instead of hardcoding content
notification = await service.create_notification(
    session=session,
    user_id="user-123",
    notification_type="order_shipped",
    template_name="order_shipped",  # Reusable template
    context={
        "order_id": "12345",
        "tracking_number": "1Z999",
    },
)
```

### 3. Monitor Queue Depth

```python
# Periodically check queue size
from example_service.features.notifications.repository import get_notification_repository

repo = get_notification_repository()
pending = await repo.find_scheduled_pending(session, limit=1000)

if len(pending) > 500:
    logger.warning(f"Large queue: {len(pending)} scheduled notifications pending")
```

## See Also

- [Phase 5 Implementation Details](../../NOTIFICATION_PHASE5_IMPLEMENTATION.md)
- [Usage Examples](../../example_service/features/notifications/examples/background_tasks_usage.py)
- [Notification Architecture](./architecture.md)
- [Taskiq Documentation](https://taskiq-python.github.io/)
