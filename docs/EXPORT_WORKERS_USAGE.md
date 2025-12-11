# Export Workers Usage Guide

## Quick Reference

### Basic Export (No Job Tracking)

```python
from example_service.workers.export.tasks import export_data_csv, export_data_json

# Export reminders to CSV
task = await export_data_csv.kiq(entity_type="reminders")
result = await task.wait_result()
print(f"Exported {result['record_count']} records to {result['filepath']}")

# Export webhooks to JSON with filters
task = await export_data_json.kiq(
    entity_type="webhooks",
    filters={"is_active": True},
)
result = await task.wait_result()

# Export with specific fields only
task = await export_data_csv.kiq(
    entity_type="reminders",
    fields=["id", "title", "remind_at", "is_completed"],
)
result = await task.wait_result()

# Export with S3 upload
task = await export_data_csv.kiq(
    entity_type="audit_logs",
    upload_to_s3=True,
)
result = await task.wait_result()
if result.get("s3_uri"):
    print(f"Uploaded to S3: {result['s3_uri']}")
```

### Export with Job Tracking (Recommended for Production)

```python
from example_service.infra.tasks.jobs.manager import JobManager
from example_service.workers.export.tasks import export_data_csv

async def export_with_tracking(session):
    # Step 1: Create job in database
    job_manager = JobManager(session)
    job = await job_manager.submit(
        tenant_id="tenant-123",
        task_name="export_reminders_csv",
        args={
            "entity_type": "reminders",
            "filters": {"is_completed": False},
        },
        priority=JobPriority.NORMAL,
        labels={"export_type": "reminders", "format": "csv"},
    )

    # Step 2: Enqueue export task with job_id
    await export_data_csv.kiq(
        entity_type="reminders",
        filters={"is_completed": False},
        job_id=str(job.id),
    )

    return job.id

# Later: Check job status
async def check_export_status(session, job_id):
    job_manager = JobManager(session)
    job = await job_manager.get(job_id, include_relations=True)

    print(f"Status: {job.status}")
    print(f"Progress: {job.progress.percentage}%")

    if job.status == JobStatus.COMPLETED:
        print(f"File: {job.result_data['file_path']}")
        print(f"Records: {job.result_data['record_count']}")
    elif job.status == JobStatus.FAILED:
        print(f"Error: {job.error_message}")
```

## Supported Entities

The following entities can be exported:

| Entity Type    | Display Name | Exportable | Importable | Notes                    |
|---------------|--------------|------------|------------|--------------------------|
| `reminders`   | Reminders    | Yes        | Yes        | Full support             |
| `files`       | Files        | Yes        | No         | File metadata only       |
| `webhooks`    | Webhooks     | Yes        | Yes        | Including secrets        |
| `audit_logs`  | Audit Logs   | Yes        | No         | Read-only audit trail    |

To see all supported entities programmatically:
```python
from example_service.features.datatransfer.service import DataTransferService

service = DataTransferService(session)
entities = service.get_supported_entities()
for entity in entities:
    print(f"{entity.name}: {entity.display_name} (exportable: {entity.exportable})")
```

## Available Filters

### Simple Equality Filters (Deprecated but Still Works)
```python
filters = {"is_completed": True, "notification_sent": False}
```

### Advanced Filters (Recommended)
```python
from example_service.features.datatransfer.schemas import FilterCondition, FilterOperator

# Use advanced filters directly with DataTransferService
# Note: Worker tasks currently only support simple filters
# For advanced filtering, use DataTransferService directly:

service = DataTransferService(session)
request = ExportRequest(
    entity_type="reminders",
    format=ExportFormat.CSV,
    filter_conditions=[
        FilterCondition(field="created_at", operator=FilterOperator.GTE, value="2024-01-01"),
        FilterCondition(field="title", operator=FilterOperator.CONTAINS, value="urgent"),
        FilterCondition(field="status", operator=FilterOperator.IN, value=["active", "pending"]),
    ],
)
result = await service.export(request)
```

## Export Result Structure

Both `export_data_csv` and `export_data_json` return:

```python
{
    "status": "success",  # or "error"
    "format": "csv",  # or "json"
    "model": "reminders",  # For backward compatibility
    "entity_type": "reminders",  # Preferred field
    "filepath": "/path/to/export/reminders_20241210_123456.csv",
    "filename": "reminders_20241210_123456.csv",
    "record_count": 150,
    "size_bytes": 45678,
    "size_kb": 44.61,
    "timestamp": "20241210_123456",
    "export_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "s3_uri": "s3://bucket/exports/reminders/reminders_20241210_123456.csv",  # If uploaded
}
```

Error response:
```python
{
    "status": "error",
    "reason": "Error message here",
    "entity_type": "reminders",
    "format": "csv",
}
```

## Job Tracking Benefits

When using job tracking (`job_id` parameter):

1. **Persistent Status**: Job state survives worker restarts
2. **Audit Trail**: Complete history of state transitions
3. **Result Storage**: Export metadata stored in database
4. **Error Tracking**: Failed exports tracked with error messages
5. **Monitoring**: Query job status from any service instance
6. **Progress Updates**: (TODO - not yet implemented)

## Error Handling

The workers implement comprehensive error handling:

```python
try:
    result = await export_data_csv.kiq(entity_type="reminders")
    result = await result.wait_result()
except Exception as e:
    # Worker task failed and was retried 3 times
    logger.error(f"Export failed: {e}")

    # If using job tracking, check job status for details
    job = await job_manager.get(job_id)
    if job.status == JobStatus.FAILED:
        print(f"Job failed: {job.error_message}")
```

Workers automatically retry up to 3 times on error.

## Migration from Old API

If you're using the old `model_name` parameter:

```python
# OLD (deprecated but still works)
await export_data_csv.kiq(model_name="reminders")

# NEW (recommended)
await export_data_csv.kiq(entity_type="reminders")
```

You'll see a deprecation warning:
```
DeprecationWarning: Parameter 'model_name' is deprecated and will be removed in a future version.
Use 'entity_type' instead.
```

## Performance Considerations

### Large Exports
For large datasets (>10,000 records):

1. **Use Job Tracking**: Monitor progress and handle failures
2. **Consider Streaming**: For very large exports, use `DataTransferService.stream_export()` directly
3. **Set Timeouts**: Configure appropriate task timeouts
4. **Schedule Off-Peak**: Run during low-traffic periods

### S3 Uploads
- Uploads happen synchronously after export completes
- For very large files, consider async upload or separate upload task
- Upload failures are logged but don't fail the export

## Common Patterns

### Scheduled Daily Exports
```python
from example_service.infra.tasks.scheduler import scheduler

@scheduler.task(cron("0 2 * * *"))  # 2 AM daily
async def scheduled_daily_export():
    await export_data_csv.kiq(
        entity_type="audit_logs",
        upload_to_s3=True,
    )
```

### Export with Notification
```python
async def export_and_notify(session, email: str):
    job_manager = JobManager(session)
    job = await job_manager.submit(
        tenant_id="tenant-123",
        task_name="export_reminders",
        args={"entity_type": "reminders"},
        webhook_url=f"https://api.example.com/notifications/email?to={email}",
    )

    await export_data_csv.kiq(
        entity_type="reminders",
        job_id=str(job.id),
    )
```

### Bulk Exports
```python
async def export_all_entities(session):
    entities = ["reminders", "webhooks", "files", "audit_logs"]
    job_ids = []

    for entity_type in entities:
        job_manager = JobManager(session)
        job = await job_manager.submit(
            tenant_id="tenant-123",
            task_name=f"export_{entity_type}",
            args={"entity_type": entity_type},
            labels={"bulk_export": "true", "batch": "2024-12-10"},
        )

        await export_data_csv.kiq(
            entity_type=entity_type,
            upload_to_s3=True,
            job_id=str(job.id),
        )

        job_ids.append(job.id)

    return job_ids
```

## Troubleshooting

### Export Returns Error Status
```python
result = await export_data_csv.kiq(entity_type="reminders")
if result["status"] == "error":
    # Check the error reason
    print(f"Export failed: {result['reason']}")

    # Common issues:
    # - Unknown entity type
    # - Invalid filters
    # - Database connection issues
    # - File system permissions
```

### Job Tracking Not Working
```python
# Ensure job_id is valid UUID string
from uuid import UUID

try:
    UUID(job_id)  # Validates format
except ValueError:
    print(f"Invalid job_id: {job_id}")

# Check job exists in database
job = await job_manager.get(UUID(job_id))
if job is None:
    print(f"Job not found: {job_id}")
```

### S3 Upload Failures
```python
result = await export_data_csv.kiq(entity_type="reminders", upload_to_s3=True)

if "s3_error" in result:
    print(f"S3 upload failed: {result['s3_error']}")
    # Export file still available locally at result['filepath']
elif "s3_skipped" in result:
    print(f"S3 not configured: {result['s3_skipped']}")
```

## API Reference

### `export_data_csv()`

```python
async def export_data_csv(
    model_name: str | None = None,  # DEPRECATED
    entity_type: str | None = None,  # Use this
    filters: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    upload_to_s3: bool = False,
    job_id: str | None = None,
) -> dict
```

### `export_data_json()`

```python
async def export_data_json(
    model_name: str | None = None,  # DEPRECATED
    entity_type: str | None = None,  # Use this
    filters: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    upload_to_s3: bool = False,
    job_id: str | None = None,
) -> dict
```

### `list_exports()`

```python
async def list_exports() -> dict
```

Returns:
```python
{
    "status": "success",
    "export_dir": "/path/to/exports",
    "count": 5,
    "exports": [
        {
            "filename": "reminders_20241210_123456.csv",
            "path": "/path/to/exports/reminders_20241210_123456.csv",
            "size_bytes": 45678,
            "size_kb": 44.61,
            "modified": "2024-12-10T12:34:56+00:00",
        },
        # ...
    ],
}
```
