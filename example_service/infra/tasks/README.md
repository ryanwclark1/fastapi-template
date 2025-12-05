# Task Execution Architecture

This document explains the architectural decisions and design patterns used in the task execution infrastructure.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Why APScheduler + Taskiq?](#why-apscheduler--taskiq)
- [Alternative: Native Taskiq Scheduler](#alternative-native-taskiq-scheduler)
- [Key Components](#key-components)
- [Task Execution Flow](#task-execution-flow)
- [Middleware Stack](#middleware-stack)
- [Result Backends](#result-backends)
- [Production Patterns](#production-patterns)
- [Common Pitfalls](#common-pitfalls)

---

## Architecture Overview

Our task system uses a **two-tier architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Application Process                                 │
│  ┌──────────────────┐         ┌──────────────────────┐     │
│  │   APScheduler    │ ────▶   │   Taskiq Broker      │     │
│  │  (Scheduling)    │         │  (Task Enqueueing)   │     │
│  └──────────────────┘         └──────────────────────┘     │
│         │                              │                     │
│         │ Cron/Interval               │ .kiq()             │
│         │ Triggers                     │                     │
│         ▼                              ▼                     │
│  ┌──────────────────┐         ┌──────────────────────┐     │
│  │  Task Wrappers   │ ────▶   │   RabbitMQ Queue     │     │
│  │  (async funcs)   │         │   (Message Broker)   │     │
│  └──────────────────┘         └──────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                                         │
                                         │ AMQP Protocol
                                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Taskiq Worker Process (Separate)                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │   Task Execution                                      │  │
│  │   • Consumes from RabbitMQ                           │  │
│  │   • Executes @broker.task() functions                │  │
│  │   • Stores results in Redis/PostgreSQL               │  │
│  │   • Emits metrics and traces                         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │   Results   │
                                  │   Backend   │
                                  │ (Redis/PG)  │
                                  └─────────────┘
```

### Key Design Principle

**Separation of Concerns:**
- **APScheduler**: Handles WHEN tasks run (scheduling logic)
- **Taskiq**: Handles HOW tasks run (execution, retries, results)
- **RabbitMQ**: Handles WHERE tasks run (distribution to workers)

---

## Why APScheduler + Taskiq?

### The Problem

We need to:
1. Schedule tasks to run at specific times (cron expressions, intervals)
2. Execute tasks asynchronously in background workers
3. Retry failed tasks with backoff
4. Track task execution history
5. Monitor task performance
6. Scale workers independently

### Our Solution: Two-Tier Architecture

We chose **APScheduler for scheduling** + **Taskiq for execution** instead of Taskiq's native scheduler.

#### Advantages of APScheduler + Taskiq

| Feature | APScheduler + Taskiq | Native Taskiq Scheduler |
|---------|---------------------|------------------------|
| **Runtime Control** | ✅ pause/resume jobs without restart | ❌ Must redeploy to change schedules |
| **Dynamic Schedules** | ✅ Add/remove jobs via API | ❌ Static schedules defined at startup |
| **Job Monitoring** | ✅ Real-time job status API | ⚠️ Limited introspection |
| **Misfire Handling** | ✅ Sophisticated policies | ⚠️ Basic handling |
| **Timezone Support** | ✅ Per-job timezone support | ⚠️ Global timezone only |
| **Job Coalescing** | ✅ Multiple missed runs → single execution | ❌ Not supported |
| **Persistence** | ✅ Job state survives restarts | ⚠️ Must be reconfigured |
| **Maturity** | ✅ Battle-tested since 2009 | ⚠️ Newer (2021) |

#### Code Comparison

**APScheduler Approach (Our Choice):**
```python
# infra/tasks/scheduler.py

# Step 1: Define Taskiq task
@broker.task()
async def cleanup_task() -> dict:
    # Task logic here
    return {"status": "success"}

# Step 2: APScheduler wrapper
async def _schedule_cleanup():
    await cleanup_task.kiq()  # Enqueue to Taskiq

# Step 3: Schedule with APScheduler
scheduler.add_job(
    func=_schedule_cleanup,
    trigger=CronTrigger(hour=2, minute=0),
    id="cleanup_sessions",
    name="Cleanup expired sessions",
)

# Step 4: Runtime control (no restart needed!)
scheduler.pause_job("cleanup_sessions")  # Pause
scheduler.resume_job("cleanup_sessions")  # Resume
scheduler.reschedule_job("cleanup_sessions", trigger=...)  # Change schedule
```

**Native Taskiq Scheduler Approach:**
```python
# Alternative approach (simpler but less flexible)

@broker.task(
    schedule=[{"cron": "0 2 * * *"}]  # Schedule defined here
)
async def cleanup_task() -> dict:
    # Task logic here
    return {"status": "success"}

# To change schedule: Must edit code and restart worker
# To pause job: Must comment out or remove schedule
# No runtime control without code changes
```

### When to Use Native Taskiq Scheduler

The native Taskiq scheduler is simpler and sufficient for:
- **Small applications** with few scheduled tasks
- **Static schedules** that rarely change
- **Simple cron patterns** without complex logic
- **Prototyping** and development

Use APScheduler when you need:
- **Production-grade** reliability and monitoring
- **Runtime control** (pause/resume/modify schedules)
- **Complex scheduling** (multiple triggers, dependencies)
- **Enterprise features** (audit logs, SLA monitoring)

---

## Key Components

### 1. Broker (`infra/tasks/broker.py`)

The broker is the core component that:
- Connects to RabbitMQ for task distribution
- Connects to Redis/PostgreSQL for result storage
- Registers middleware for cross-cutting concerns
- Imports all task modules for worker discovery

```python
broker = (
    AioPikaBroker(
        url=rabbit_settings.get_url(),
        queue_name=rabbit_settings.get_prefixed_queue("taskiq-tasks"),
    )
    .with_result_backend(result_backend)
    .with_middlewares(
        SimpleRetryMiddleware(),      # Retry failed tasks
        MetricsMiddleware(),           # Prometheus metrics
        TracingMiddleware(),           # OpenTelemetry tracing
        TrackingMiddleware(),          # Task history
    )
)
```

**Key Decision:** We use `taskiq-aio-pika` (RabbitMQ) instead of Redis because:
- **Message Durability**: RabbitMQ persists messages to disk
- **Delivery Guarantees**: At-least-once delivery with acks
- **High Availability**: Built-in clustering and mirroring
- **Backpressure**: Automatic flow control when consumers are slow
- **Enterprise Features**: Dead letter exchanges, TTL, priority queues

### 2. Scheduler (`infra/tasks/scheduler.py`)

The scheduler runs **in the FastAPI process** and:
- Loads scheduled jobs at startup
- Triggers jobs based on cron/interval schedules
- Calls `.kiq()` to enqueue tasks to workers
- Provides runtime control APIs

```python
# Setup during FastAPI startup
setup_scheduled_jobs()  # Register jobs
await start_scheduler()  # Start APScheduler

# Jobs automatically enqueue to Taskiq workers
```

### 3. Middleware (`infra/tasks/middleware.py`)

Middleware provides cross-cutting concerns. **Order matters!**

```python
.with_middlewares(
    SimpleRetryMiddleware(),    # 1. Must be first - handles retries
    MetricsMiddleware(),         # 2. Records Prometheus metrics
    TracingMiddleware(),         # 3. Creates OpenTelemetry spans
    TrackingMiddleware(),        # 4. Stores execution history
)
```

**Why this order?**
1. **SimpleRetryMiddleware first**: Wraps entire execution, retries on failure
2. **MetricsMiddleware second**: Records metrics for all attempts (including retries)
3. **TracingMiddleware third**: Creates distributed trace spans
4. **TrackingMiddleware last**: Records final execution state

### 4. Result Backend (`infra/results/`)

We support **two result backends** via `TASK_RESULT_BACKEND` setting:

#### Redis Backend (Default)
```python
# Fast, in-memory storage
result_backend = RedisAsyncResultBackend(
    redis_url=redis_settings.get_url(),
    result_ex_time=3600,  # TTL: 1 hour
)
```

**Use when:**
- High throughput (>1000 tasks/sec)
- Results are ephemeral (don't need long-term storage)
- Fast result lookups are critical

#### PostgreSQL Backend
```python
# Durable, queryable storage
result_backend = PostgresAsyncResultBackend(
    dsn=db_settings.get_sqlalchemy_url(),
    result_ttl_seconds=86400,  # TTL: 24 hours
)
```

**Use when:**
- Need to query task history (analytics, debugging)
- Results must survive Redis restarts
- Long-term audit trails required
- Already have PostgreSQL (no extra infrastructure)

**Configuration:**
```bash
# .env
TASK_RESULT_BACKEND=redis    # or 'postgres'
TASK_TRACKING_RETENTION_HOURS=24
```

### 5. Tracking (`infra/tasks/tracking/`)

Tracks task execution history for monitoring and debugging:

```python
# Query recent tasks
tracker = get_tracker()
recent = await tracker.get_recent_tasks(limit=100)

# Query by status
failed = await tracker.get_tasks_by_status("failed")

# Query by time range
tasks = await tracker.get_tasks_in_range(
    start=datetime.now() - timedelta(hours=1),
    end=datetime.now(),
)
```

**Storage Options:**
- **RedisTracker**: Fast, ephemeral tracking
- **PostgresTracker**: Persistent, queryable tracking

---

## Task Execution Flow

### 1. Schedule Time Arrives

```
APScheduler (in FastAPI process)
    │
    │ Cron trigger fires
    ▼
_schedule_cleanup()  ──────▶  cleanup_task.kiq()
    │                              │
    │                              │ Serializes task
    │                              ▼
    │                         RabbitMQ Queue
    │                         (Persistent)
```

### 2. Worker Picks Up Task

```
Taskiq Worker Process
    │
    │ Polls RabbitMQ
    ▼
Consumer receives message
    │
    │ Deserializes
    ▼
Middleware chain executes
    │
    ├──▶ SimpleRetryMiddleware (retry logic)
    │    ├──▶ MetricsMiddleware (record start)
    │    │    ├──▶ TracingMiddleware (create span)
    │    │    │    ├──▶ TrackingMiddleware (save to DB)
    │    │    │    │    │
    │    │    │    │    ▼
    │    │    │    │    cleanup_task() executes
    │    │    │    │    │
    │    │    │    │    ▼
    │    │    │    │    Return result
    │    │    │    │
    │    │    │    └──▶ Save execution record
    │    │    │
    │    │    └──▶ Close trace span
    │    │
    │    └──▶ Record metrics (duration, status)
    │
    └──▶ If error: retry with backoff
```

### 3. Result Storage

```
Task completes successfully
    │
    ▼
Result Backend (Redis or PostgreSQL)
    │
    ├──▶ Store return value
    ├──▶ Store metadata (duration, status)
    ├──▶ Set TTL (auto-cleanup)
    │
    ▼
Result available for retrieval
```

### 4. Result Retrieval

```python
# From FastAPI endpoint or another task
task = await some_task.kiq(data="example")

# Wait for result (blocks until complete)
result = await task.wait_result(timeout=60)

if result.is_err:
    print(f"Task failed: {result.error}")
else:
    print(f"Task succeeded: {result.return_value}")
```

---

## Middleware Stack

### SimpleRetryMiddleware

Handles automatic retries with exponential backoff.

```python
@broker.task(
    retry_on_error=True,    # Enable retries
    max_retries=3,           # Max 3 attempts
)
async def flaky_task():
    # If this raises an exception, will retry 3 times
    # with exponential backoff: 1s, 2s, 4s
    pass
```

**Backoff Strategy:**
- Attempt 1: Immediate
- Attempt 2: 1 second delay
- Attempt 3: 2 seconds delay
- Attempt 4: 4 seconds delay

### MetricsMiddleware

Emits Prometheus metrics for observability.

**Metrics Exposed:**
```python
# Task execution count by status
taskiq_tasks_total{task_name="cleanup", status="success"} 42
taskiq_tasks_total{task_name="cleanup", status="failed"} 3

# Task execution duration
taskiq_task_duration_seconds{task_name="cleanup"} 2.5

# Active tasks (currently executing)
taskiq_tasks_active{task_name="cleanup"} 5
```

**Prometheus Queries:**
```promql
# Success rate
rate(taskiq_tasks_total{status="success"}[5m])
  / rate(taskiq_tasks_total[5m])

# P95 latency
histogram_quantile(0.95,
  rate(taskiq_task_duration_seconds_bucket[5m]))
```

### TracingMiddleware

Creates OpenTelemetry spans for distributed tracing.

**Trace Structure:**
```
FastAPI Request
  └─▶ Schedule Task (HTTP span)
       └─▶ Task Execution (Taskiq span)
            ├─▶ Database Query (SQLAlchemy span)
            ├─▶ External API Call (HTTP span)
            └─▶ Cache Operation (Redis span)
```

**Integration with Jaeger/Zipkin:**
```python
# Traces are automatically exported to configured backend
# View in Jaeger UI to see full request flow
```

### TrackingMiddleware

Stores execution records in Redis or PostgreSQL.

**Schema:**
```python
{
    "task_id": "abc-123",
    "task_name": "cleanup_task",
    "status": "success",
    "started_at": "2025-01-15T10:00:00Z",
    "completed_at": "2025-01-15T10:00:02Z",
    "duration_ms": 2000,
    "args": [],
    "kwargs": {},
    "result": {"deleted": 100},
    "error": null,
}
```

---

## Result Backends

### Performance Comparison

| Backend | Read Latency | Write Latency | Storage | Queryability |
|---------|-------------|---------------|---------|--------------|
| **Redis** | ~1ms | ~1ms | In-memory | Limited (by key) |
| **PostgreSQL** | ~5ms | ~10ms | Persistent | Full SQL |

### Choosing a Backend

#### Use Redis When:
```python
# High throughput, ephemeral results
TASK_RESULT_BACKEND=redis
TASK_REDIS_RESULT_TTL_SECONDS=3600  # 1 hour
```

**Best for:**
- Fast task polling
- Short-lived results
- High request rate (>1000 tasks/sec)
- Results don't need to survive restarts

#### Use PostgreSQL When:
```python
# Persistent storage, complex queries
TASK_RESULT_BACKEND=postgres
TASK_TRACKING_RETENTION_HOURS=168  # 7 days
```

**Best for:**
- Audit requirements
- Analytics and reporting
- Long-term debugging
- Complex queries (e.g., "show all failed tasks in last week")

**Query Examples:**
```sql
-- Find slow tasks
SELECT task_name, AVG(duration_ms) as avg_duration
FROM task_execution_records
WHERE created_at > NOW() - INTERVAL '1 day'
GROUP BY task_name
ORDER BY avg_duration DESC;

-- Find failure patterns
SELECT task_name, error, COUNT(*) as count
FROM task_execution_records
WHERE status = 'failed'
GROUP BY task_name, error
ORDER BY count DESC;
```

---

## Production Patterns

### 1. Task Chaining

Sequential execution with result passing:

```python
@broker.task()
async def step1() -> dict:
    return {"data": "from step1"}

@broker.task()
async def step2(data: dict) -> dict:
    # Use data from step1
    return {"result": f"processed {data['data']}"}

# Orchestrator
@broker.task()
async def workflow():
    result1 = await step1.kiq()
    data = await result1.wait_result(timeout=30)

    result2 = await step2.kiq(data=data.return_value)
    final = await result2.wait_result(timeout=30)

    return final.return_value
```

**See:** `workers/reports/tasks.py` for full examples.

### 2. Parallel Execution (Fan-Out/Fan-In)

Process multiple items concurrently:

```python
@broker.task()
async def process_item(item_id: str) -> dict:
    # Process single item
    return {"item_id": item_id, "status": "done"}

@broker.task()
async def batch_process(item_ids: list[str]) -> dict:
    # Fan-out: Launch all tasks in parallel
    tasks = [await process_item.kiq(item_id=id) for id in item_ids]

    # Fan-in: Wait for all to complete
    results = [await task.wait_result(timeout=60) for task in tasks]

    return {
        "total": len(results),
        "successful": sum(1 for r in results if not r.is_err),
    }
```

**See:** `workers/reports/tasks.py:batch_generate_reports()`.

### 3. Conditional Workflows

Branching logic based on intermediate results:

```python
@broker.task()
async def conditional_workflow(threshold: int):
    # Step 1: Collect data
    data_task = await collect_data.kiq()
    data = await data_task.wait_result()

    # Step 2: Branch based on result
    if data.return_value["count"] > threshold:
        # High priority path
        await send_alert.kiq(urgent=True)
        await detailed_processing.kiq(data.return_value)
    else:
        # Normal priority path
        await standard_processing.kiq(data.return_value)
```

**See:** `workers/reports/tasks.py:generate_conditional_report()`.

### 4. Saga Pattern (Compensating Transactions)

Distributed transactions with rollback:

```python
@broker.task()
async def payment_saga(order_id: str):
    completed_steps = []

    try:
        # Step 1: Reserve inventory
        await reserve_inventory(order_id)
        completed_steps.append("reserve_inventory")

        # Step 2: Charge payment
        await charge_payment(order_id)
        completed_steps.append("charge_payment")

        # Step 3: Create shipment
        await create_shipment(order_id)
        completed_steps.append("create_shipment")

        return {"status": "success"}

    except Exception as e:
        # Rollback in reverse order
        if "create_shipment" in completed_steps:
            await cancel_shipment(order_id)
        if "charge_payment" in completed_steps:
            await refund_payment(order_id)
        if "reserve_inventory" in completed_steps:
            await release_inventory(order_id)

        return {"status": "failed", "error": str(e)}
```

**See:** `workers/examples/advanced_patterns.py:payment_saga()`.

### 5. Circuit Breaker

Prevent cascading failures:

```python
circuit_state = {"failures": 0, "state": "closed"}

@broker.task()
async def call_external_api():
    if circuit_state["state"] == "open":
        # Fail fast, don't hammer failing service
        return {"error": "circuit breaker open"}

    try:
        result = await external_api_call()
        circuit_state["failures"] = 0
        return result
    except Exception as e:
        circuit_state["failures"] += 1
        if circuit_state["failures"] >= 5:
            circuit_state["state"] = "open"
        raise
```

**See:** `workers/examples/advanced_patterns.py:call_external_api_with_circuit_breaker()`.

---

## Common Pitfalls

### ❌ Pitfall 1: Blocking I/O in Async Tasks

```python
# BAD: Blocks the event loop
@broker.task()
async def bad_task():
    time.sleep(5)  # Blocks worker!
    return "done"

# GOOD: Use asyncio.sleep()
@broker.task()
async def good_task():
    await asyncio.sleep(5)
    return "done"
```

### ❌ Pitfall 2: Large Task Arguments

```python
# BAD: Serializing 100MB of data
@broker.task()
async def bad_task(huge_data: list):
    # huge_data is serialized to RabbitMQ!
    pass

await bad_task.kiq(huge_data=list_of_1_million_items)

# GOOD: Pass reference, fetch in task
@broker.task()
async def good_task(data_key: str):
    # Fetch from database/S3 inside task
    data = await fetch_from_storage(data_key)
    pass

await good_task.kiq(data_key="s3://bucket/file.json")
```

### ❌ Pitfall 3: Not Handling Task Failures

```python
# BAD: Fire and forget
await some_task.kiq()
# What if it fails? You'll never know!

# GOOD: Check result or use callbacks
task = await some_task.kiq()
result = await task.wait_result(timeout=60)

if result.is_err:
    logger.error(f"Task failed: {result.error}")
    # Handle failure (retry, alert, etc.)
```

### ❌ Pitfall 4: Infinite Retry Loops

```python
# BAD: Will retry forever
@broker.task(retry_on_error=True, max_retries=999)
async def bad_task():
    raise ValueError("Always fails")

# GOOD: Reasonable limits + exponential backoff
@broker.task(retry_on_error=True, max_retries=3)
async def good_task():
    try:
        # Attempt operation
        pass
    except ValueError:
        # Don't retry on validation errors
        raise
    except ConnectionError:
        # Retry on transient errors
        raise
```

### ❌ Pitfall 5: No Idempotency

```python
# BAD: Running twice creates duplicate charges
@broker.task()
async def bad_charge_payment(user_id: str, amount: float):
    await charge_credit_card(user_id, amount)

# GOOD: Idempotent with deduplication key
@broker.task()
async def good_charge_payment(
    idempotency_key: str,
    user_id: str,
    amount: float,
):
    if await already_processed(idempotency_key):
        return await get_cached_result(idempotency_key)

    result = await charge_credit_card(user_id, amount)
    await cache_result(idempotency_key, result)
    return result
```

**See:** `workers/examples/advanced_patterns.py:idempotent_payment()`.

---

## Running the System

### Development

```bash
# Terminal 1: Start FastAPI (includes APScheduler)
uvicorn example_service.main:app --reload

# Terminal 2: Start Taskiq worker
taskiq worker example_service.infra.tasks.broker:broker --reload

# Terminal 3: Monitor tasks
taskiq metrics example_service.infra.tasks.broker:broker
```

### Production

```bash
# Docker Compose (see docker-compose.yml)
docker-compose up -d

# Or separate processes
# 1. FastAPI with APScheduler
gunicorn example_service.main:app -w 4 -k uvicorn.workers.UvicornWorker

# 2. Taskiq workers (multiple instances)
taskiq worker example_service.infra.tasks.broker:broker --workers 4

# 3. RabbitMQ
docker run -d -p 5672:5672 rabbitmq:3-management

# 4. Redis or PostgreSQL (for results)
docker run -d -p 6379:6379 redis:7-alpine
```

### Monitoring

**Prometheus Metrics:**
```bash
# FastAPI exposes metrics at /metrics
curl http://localhost:8000/metrics
```

**Task History:**
```python
# Via API or CLI
from example_service.infra.tasks.tracking import get_tracker

tracker = get_tracker()
recent_tasks = await tracker.get_recent_tasks(limit=100)
failed_tasks = await tracker.get_tasks_by_status("failed")
```

**APScheduler Job Status:**
```python
from example_service.infra.tasks.scheduler import get_job_status

jobs = get_job_status()
for job in jobs:
    print(f"{job['name']}: next run at {job['next_run_time']}")
```

---

## References

- [Taskiq Documentation](https://taskiq-python.github.io/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [taskiq-aio-pika](https://github.com/taskiq-python/taskiq-aio-pika)
- [RabbitMQ Best Practices](https://www.rabbitmq.com/best-practices.html)
- [OpenTelemetry Tracing](https://opentelemetry.io/docs/instrumentation/python/)

---

## Example Tasks

This template includes comprehensive examples:

1. **Basic Tasks** (`workers/`): cleanup, backup, notifications
2. **Analytics** (`workers/analytics/`): Multi-level time-series aggregation
3. **Reports** (`workers/reports/`): Task chaining, parallel execution, conditional workflows
4. **Advanced Patterns** (`workers/examples/advanced_patterns.py`): Circuit breakers, sagas, idempotency

Explore these to understand production-ready patterns!
