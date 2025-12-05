# Task System Quick Start Guide

This guide helps you understand and use the production-ready task execution system in this template.

## 🎯 What You Get

This template includes a sophisticated **two-tier task system** with:

### 🏗️ **Infrastructure** (`example_service/infra/tasks/`)
- **APScheduler**: Enterprise-grade job scheduling with runtime control
- **Taskiq**: Async task execution with RabbitMQ
- **Result Backends**: Redis (fast) or PostgreSQL (queryable)
- **Middleware Stack**: Retries, metrics, tracing, tracking
- **Job Orchestration**: Priorities, dependencies, audit trails

### 🛠️ **Workers** (`example_service/workers/`)
Production task implementations:
- **backup/**: Database backup with S3 upload
- **cache/**: Cache warming and invalidation
- **cleanup/**: Temp files, old backups, expired data
- **export/**: Data export (CSV/JSON)
- **files/**: File processing
- **notifications/**: Reminder notifications
- **webhooks/**: Webhook delivery

### 📊 **Example Patterns** (New!)
Advanced task patterns for complex workflows:

1. **Analytics** (`workers/analytics/tasks.py`):
   - Multi-level time-series aggregation (hourly → daily → weekly → monthly)
   - Incremental data processing
   - KPI computation with complex calculations
   - Trend analysis and forecasting

2. **Reports** (`workers/reports/tasks.py`):
   - **Task chaining**: Sequential execution with result passing
   - **Parallel execution**: Fan-out/fan-in batch processing
   - **Conditional workflows**: Branching logic based on results
   - Multi-step report generation and delivery

3. **Advanced Patterns** (`workers/examples/advanced_patterns.py`):
   - **Graceful degradation**: Fallback mechanisms
   - **Partial success handling**: Continue processing on errors
   - **Saga pattern**: Distributed transactions with compensating rollbacks
   - **Circuit breaker**: Prevent cascading failures
   - **Idempotency**: Safe retry without duplicate effects

---

## 🚀 Quick Start

### 1. Start the System

```bash
# Terminal 1: Start dependencies (RabbitMQ, Redis, PostgreSQL)
docker-compose up -d rabbitmq redis postgres

# Terminal 2: Start FastAPI (includes APScheduler)
uvicorn example_service.main:app --reload

# Terminal 3: Start Taskiq worker
taskiq worker example_service.infra.tasks.broker:broker --reload
```

### 2. Verify It's Working

```bash
# Check scheduled jobs
curl http://localhost:8000/api/v1/tasks/scheduled

# Kick a task manually
curl -X POST http://localhost:8000/api/v1/tasks/examples/kick \
  -H "Content-Type: application/json" \
  -d '{"data": {"test": "value"}}'

# Check task status
curl http://localhost:8000/api/v1/tasks/{task_id}/status
```

### 3. View Metrics

```bash
# Prometheus metrics
curl http://localhost:8000/metrics | grep taskiq
```

---

## 📚 Learn by Example

### Example 1: Simple Background Task

```python
# workers/my_module/tasks.py
from example_service.infra.tasks.broker import broker

@broker.task()
async def send_email(recipient: str, subject: str, body: str) -> dict:
    # Task logic here
    await email_service.send(recipient, subject, body)
    return {"status": "sent", "recipient": recipient}
```

**Usage from FastAPI endpoint:**
```python
@router.post("/send")
async def send_email_endpoint(email: EmailRequest):
    # Enqueue task (non-blocking)
    task = await send_email.kiq(
        recipient=email.recipient,
        subject=email.subject,
        body=email.body,
    )
    return {"task_id": task.task_id}
```

### Example 2: Task Chaining

```python
from example_service.workers.reports.tasks import generate_and_deliver_report

# Chain multiple steps: collect → format → deliver
task = await generate_and_deliver_report.kiq(
    report_type="sales",
    start_date="2025-01-01",
    end_date="2025-01-31",
    output_format="pdf",
    recipients=["manager@example.com"],
)

# Wait for completion
result = await task.wait_result(timeout=120)
print(result.return_value)
```

**See:** `workers/reports/tasks.py` for full implementation.

### Example 3: Parallel Batch Processing

```python
from example_service.workers.reports.tasks import batch_generate_reports

# Generate multiple reports in parallel
specs = [
    {
        "report_type": "sales",
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "output_format": "pdf",
        "recipients": ["client1@example.com"],
    },
    {
        "report_type": "sales",
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "output_format": "excel",
        "recipients": ["client2@example.com"],
    },
]

task = await batch_generate_reports.kiq(
    report_specs=specs,
    parallel=True,  # Run all in parallel
)

result = await task.wait_result(timeout=300)
print(f"Success: {result.return_value['summary']['successful']}")
print(f"Failed: {result.return_value['summary']['failed']}")
```

**See:** `workers/reports/tasks.py:batch_generate_reports()`.

### Example 4: Saga Pattern (Distributed Transactions)

```python
from example_service.workers.examples.advanced_patterns import payment_saga

# Execute multi-step transaction with automatic rollback on failure
task = await payment_saga.kiq(
    order_id="order_123",
    user_id="user_456",
    amount=99.99,
)

result = await task.wait_result()

if result.return_value["status"] == "completed":
    print("Payment successful!")
else:
    # Compensating transactions were executed
    print(f"Payment failed, rolled back: {result.return_value['compensations']}")
```

**See:** `workers/examples/advanced_patterns.py:payment_saga()`.

### Example 5: Scheduled Task

```python
# 1. Define the task
@broker.task()
async def daily_cleanup() -> dict:
    # Cleanup logic
    return {"deleted": 100}

# 2. Create scheduler wrapper
async def _schedule_cleanup():
    await daily_cleanup.kiq()

# 3. Register with APScheduler (in scheduler.py)
scheduler.add_job(
    func=_schedule_cleanup,
    trigger=CronTrigger(hour=2, minute=0),  # Daily at 2 AM
    id="daily_cleanup",
    name="Daily cleanup task",
)

# 4. Runtime control (no restart needed!)
from example_service.infra.tasks.scheduler import pause_job, resume_job

pause_job("daily_cleanup")   # Pause
resume_job("daily_cleanup")  # Resume
```

---

## 🎓 Understanding the Architecture

### Why APScheduler + Taskiq?

**The Problem:** We need to schedule tasks (cron) AND execute them asynchronously (workers).

**Our Solution:** Two-tier architecture
- **APScheduler** (in FastAPI process): Decides WHEN tasks run
- **Taskiq** (separate workers): Executes HOW tasks run
- **RabbitMQ**: Distributes tasks to workers

**Alternative:** Taskiq's native scheduler
```python
@broker.task(schedule=[{"cron": "0 2 * * *"}])
async def my_task():
    pass
```

This is simpler but lacks:
- Runtime job control (pause/resume without restart)
- Job coalescing (merge multiple missed runs)
- Per-job timezone support
- Rich monitoring APIs

**When to use native scheduler:** Small apps with static schedules.
**When to use APScheduler:** Production apps needing operational flexibility.

### Execution Flow

```
1. APScheduler trigger fires
        ↓
2. Wrapper function calls task.kiq()
        ↓
3. Task serialized to RabbitMQ queue
        ↓
4. Taskiq worker picks up task
        ↓
5. Middleware chain executes:
   - SimpleRetryMiddleware (retry logic)
   - MetricsMiddleware (Prometheus metrics)
   - TracingMiddleware (OpenTelemetry traces)
   - TrackingMiddleware (execution history)
        ↓
6. Task executes
        ↓
7. Result stored in Redis/PostgreSQL
        ↓
8. Caller can retrieve result
```

### Middleware Stack (Order Matters!)

```python
broker.with_middlewares(
    SimpleRetryMiddleware(),    # 1. MUST be first (wraps retries)
    MetricsMiddleware(),         # 2. Metrics for all attempts
    TracingMiddleware(),         # 3. Distributed tracing
    TrackingMiddleware(),        # 4. Execution history
)
```

**Why this order?**
- SimpleRetryMiddleware wraps entire execution (including retries)
- MetricsMiddleware records metrics for each retry attempt
- TracingMiddleware creates spans for distributed tracing
- TrackingMiddleware stores final execution state

**Don't reorder these!** Changing order breaks retry logic or metrics accuracy.

---

## 🏭 Production Patterns

### Pattern 1: Task Chaining (Sequential Execution)

Use when steps must run in order and pass data:

```python
# Step 1 → Step 2 → Step 3
result1 = await step1.kiq()
data = await result1.wait_result()

result2 = await step2.kiq(data=data.return_value)
final = await result2.wait_result()
```

**Example:** `workers/reports/tasks.py:generate_and_deliver_report()`

### Pattern 2: Fan-Out/Fan-In (Parallel Execution)

Use for independent tasks that can run simultaneously:

```python
# Launch all tasks in parallel
tasks = [await process_item.kiq(item) for item in items]

# Wait for all to complete
results = [await task.wait_result() for task in tasks]
```

**Example:** `workers/reports/tasks.py:batch_generate_reports()`

### Pattern 3: Conditional Workflows

Use for branching logic based on intermediate results:

```python
data = await collect_data.kiq()
result = await data.wait_result()

if result.return_value["amount"] > threshold:
    await high_priority_path.kiq(result.return_value)
else:
    await standard_path.kiq(result.return_value)
```

**Example:** `workers/reports/tasks.py:generate_conditional_report()`

### Pattern 4: Saga (Distributed Transactions)

Use for multi-step operations that need rollback:

```python
completed_steps = []
try:
    await reserve_inventory()
    completed_steps.append("inventory")

    await charge_payment()
    completed_steps.append("payment")

    await create_shipment()
    completed_steps.append("shipment")
except Exception:
    # Rollback in reverse order
    for step in reversed(completed_steps):
        await compensate(step)
```

**Example:** `workers/examples/advanced_patterns.py:payment_saga()`

### Pattern 5: Circuit Breaker

Use to prevent cascading failures:

```python
if circuit_breaker.is_open():
    return fallback_response()

try:
    result = await external_api_call()
    circuit_breaker.record_success()
    return result
except Exception:
    circuit_breaker.record_failure()
    if circuit_breaker.should_open():
        circuit_breaker.open()
    raise
```

**Example:** `workers/examples/advanced_patterns.py:call_external_api_with_circuit_breaker()`

---

## ⚙️ Configuration

### Environment Variables

```bash
# Task Result Backend (redis or postgres)
TASK_RESULT_BACKEND=redis

# Redis Result Backend Settings
TASK_REDIS_RESULT_TTL_SECONDS=3600
TASK_REDIS_KEY_PREFIX=taskiq:result:

# PostgreSQL Result Backend Settings
TASK_TRACKING_RETENTION_HOURS=168  # 7 days

# RabbitMQ Settings
RABBIT_HOST=localhost
RABBIT_PORT=5672
RABBIT_USER=guest
RABBIT_PASSWORD=guest
RABBIT_VHOST=/
RABBIT_QUEUE_PREFIX=example-service
```

### Choosing a Result Backend

**Use Redis when:**
- High throughput (>1000 tasks/sec)
- Fast result lookups are critical (~1ms latency)
- Results are ephemeral (don't need long-term storage)

**Use PostgreSQL when:**
- Need to query task history (SQL analytics)
- Audit trails required
- Results must survive restarts
- Already have PostgreSQL (no extra infrastructure)

### Scaling Workers

```bash
# Run multiple workers for high throughput
taskiq worker example_service.infra.tasks.broker:broker --workers 4

# Or run multiple worker processes
for i in {1..4}; do
  taskiq worker example_service.infra.tasks.broker:broker &
done
```

---

## 📊 Monitoring

### Prometheus Metrics

```bash
# Task execution counts
taskiq_tasks_total{task_name="cleanup", status="success"} 42
taskiq_tasks_total{task_name="cleanup", status="failed"} 3

# Task duration
taskiq_task_duration_seconds{task_name="cleanup"} 2.5

# Active tasks
taskiq_tasks_active{task_name="cleanup"} 5
```

### Task History Queries

```python
from example_service.infra.tasks.tracking import get_tracker

tracker = get_tracker()

# Recent tasks
recent = await tracker.get_recent_tasks(limit=100)

# Failed tasks
failed = await tracker.get_tasks_by_status("failed")

# Time range query
tasks = await tracker.get_tasks_in_range(
    start=datetime.now() - timedelta(hours=1),
    end=datetime.now(),
)
```

### Scheduled Job Status

```python
from example_service.infra.tasks.scheduler import get_job_status

jobs = get_job_status()
for job in jobs:
    print(f"{job['name']}: next run at {job['next_run_time']}")
```

---

## 🐛 Common Pitfalls

### ❌ Don't: Block the Event Loop

```python
# BAD
@broker.task()
async def bad_task():
    time.sleep(5)  # Blocks worker!

# GOOD
@broker.task()
async def good_task():
    await asyncio.sleep(5)
```

### ❌ Don't: Pass Large Data as Arguments

```python
# BAD (serializes 100MB to RabbitMQ)
await process_data.kiq(huge_list=list_of_1_million_items)

# GOOD (pass reference, fetch in task)
await process_data.kiq(data_key="s3://bucket/file.json")
```

### ❌ Don't: Ignore Task Failures

```python
# BAD (fire and forget)
await some_task.kiq()

# GOOD (check result)
task = await some_task.kiq()
result = await task.wait_result(timeout=60)
if result.is_err:
    logger.error(f"Task failed: {result.error}")
```

### ❌ Don't: Forget Idempotency

```python
# BAD (running twice = duplicate charges)
@broker.task()
async def charge_payment(user_id, amount):
    await charge_card(user_id, amount)

# GOOD (idempotent with deduplication)
@broker.task()
async def charge_payment(idempotency_key, user_id, amount):
    if await already_processed(idempotency_key):
        return await get_cached_result(idempotency_key)
    result = await charge_card(user_id, amount)
    await cache_result(idempotency_key, result)
    return result
```

---

## 📖 Further Reading

### Documentation
- **Architecture Deep Dive**: `example_service/infra/tasks/README.md`
- **Taskiq Docs**: https://taskiq-python.github.io/
- **APScheduler Docs**: https://apscheduler.readthedocs.io/

### Example Code
- **Analytics Aggregation**: `example_service/workers/analytics/tasks.py`
- **Report Workflows**: `example_service/workers/reports/tasks.py`
- **Advanced Patterns**: `example_service/workers/examples/advanced_patterns.py`
- **FastAPI Integration**: `example_service/workers/examples/fastapi_integration.py`

### Production Examples
All example tasks include:
- ✅ Proper error handling
- ✅ Retry strategies
- ✅ Logging with structured context
- ✅ Result validation
- ✅ Type hints

---

## 🎯 Next Steps

1. **Read the architecture docs**: `example_service/infra/tasks/README.md`
2. **Explore example tasks**: Study `workers/analytics/` and `workers/reports/`
3. **Try the patterns**: Run examples in `workers/examples/advanced_patterns.py`
4. **Build your own tasks**: Follow the patterns for your specific use cases
5. **Monitor in production**: Set up Prometheus/Grafana dashboards

---

## 🤝 Support

Questions? Check:
- 📖 Architecture documentation: `example_service/infra/tasks/README.md`
- 💡 Example code: `example_service/workers/`
- 🌐 Taskiq docs: https://taskiq-python.github.io/

Happy task building! 🚀
