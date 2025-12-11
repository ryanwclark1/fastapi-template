# DataTransfer ACL Quick Start Guide

## Overview

This guide shows how to use the new ACL permissions and execution modes for the datatransfer feature.

## Permission Assignment

### For Export Access

Grant users permission to export specific entity types:

```python
# Specific entity export
permissions = ["datatransfer.export.reminders"]

# Multiple entities
permissions = [
    "datatransfer.export.reminders",
    "datatransfer.export.files",
    "datatransfer.export.webhooks",
]

# All exports
permissions = ["datatransfer.export.#"]

# Full datatransfer admin
permissions = ["datatransfer.admin"]
```

### For Import Access

Grant users permission to import specific entity types:

```python
# Specific entity import
permissions = ["datatransfer.import.reminders"]

# All imports
permissions = ["datatransfer.import.#"]

# Full admin (both import and export)
permissions = ["datatransfer.admin"]
```

### For Job Access

Grant users permission to view and download jobs:

```python
# View own jobs
permissions = ["datatransfer.read.jobs"]

# Admin access to all jobs
permissions = ["datatransfer.admin.jobs"]
```

## API Usage

### Synchronous Export (Immediate)

```bash
curl -X POST "http://localhost:8000/api/v1/data-transfer/export?execution_mode=sync" \
  -H "X-Auth-Token: your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "reminders",
    "format": "csv"
  }'
```

Response:
```json
{
  "status": "completed",
  "export_id": "abc123",
  "entity_type": "reminders",
  "format": "csv",
  "file_path": "/tmp/exports/reminders_20251210_120000.csv",
  "record_count": 150,
  "size_bytes": 45000
}
```

### Asynchronous Export (Background Job)

```bash
curl -X POST "http://localhost:8000/api/v1/data-transfer/export?execution_mode=async" \
  -H "X-Auth-Token: your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "reminders",
    "format": "csv"
  }'
```

Response:
```json
{
  "status": "pending",
  "export_id": "job-uuid-123",
  "entity_type": "reminders",
  "format": "csv",
  "started_at": "2025-12-10T12:00:00Z",
  "download_url": "/api/v1/data-transfer/jobs/job-uuid-123/download"
}
```

### Auto Mode (Automatic Selection)

System automatically chooses sync or async based on data size:

```bash
curl -X POST "http://localhost:8000/api/v1/data-transfer/export?execution_mode=auto" \
  -H "X-Auth-Token: your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "reminders",
    "format": "csv"
  }'
```

- ≤10,000 records: Synchronous execution
- >10,000 records: Asynchronous execution

### Check Job Status

```bash
curl -X GET "http://localhost:8000/api/v1/data-transfer/jobs/{job_id}" \
  -H "X-Auth-Token: your-token"
```

### Download Job Result

```bash
curl -X GET "http://localhost:8000/api/v1/data-transfer/jobs/{job_id}/download" \
  -H "X-Auth-Token: your-token" \
  -o export.csv
```

### Import with ACL

```bash
curl -X POST "http://localhost:8000/api/v1/data-transfer/import?entity_type=reminders&format=csv" \
  -H "X-Auth-Token: your-token" \
  -F "file=@data.csv"
```

## Permission Examples

### Read-Only User

User can only export, not import:

```python
permissions = [
    "datatransfer.export.reminders",
    "datatransfer.export.files",
]
```

### Data Manager

User can import and export specific entities:

```python
permissions = [
    "datatransfer.export.reminders",
    "datatransfer.export.files",
    "datatransfer.import.reminders",
    "datatransfer.import.files",
    "datatransfer.read.jobs",
]
```

### Admin User

Full access to all datatransfer operations:

```python
permissions = [
    "datatransfer.admin",
]
```

## Error Responses

### Permission Denied (403)

```json
{
  "error": "insufficient_permissions",
  "message": "Missing permission: datatransfer.export.reminders",
  "required_permission": "datatransfer.export.reminders"
}
```

### Job Not Found (404)

```json
{
  "error": "job_not_found",
  "message": "Job job-uuid-123 not found",
  "job_id": "job-uuid-123"
}
```

### Job Access Denied (403)

```json
{
  "error": "access_denied",
  "message": "You do not have permission to access this job",
  "job_id": "job-uuid-123"
}
```

## Code Examples

### Python Client

```python
import httpx

class DataTransferClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"X-Auth-Token": token}

    async def export_sync(self, entity_type: str, format: str = "csv"):
        """Synchronous export - returns immediately with file."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/data-transfer/export",
                params={"execution_mode": "sync"},
                json={"entity_type": entity_type, "format": format},
                headers=self.headers,
            )
            return response.json()

    async def export_async(self, entity_type: str, format: str = "csv"):
        """Asynchronous export - returns job ID."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/data-transfer/export",
                params={"execution_mode": "async"},
                json={"entity_type": entity_type, "format": format},
                headers=self.headers,
            )
            return response.json()

    async def get_job_status(self, job_id: str):
        """Check job status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/data-transfer/jobs/{job_id}",
                headers=self.headers,
            )
            return response.json()

    async def download_job(self, job_id: str, output_path: str):
        """Download job result file."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/data-transfer/jobs/{job_id}/download",
                headers=self.headers,
            )
            with open(output_path, "wb") as f:
                f.write(response.content)

# Usage
client = DataTransferClient("http://localhost:8000/api/v1", "your-token")

# Sync export
result = await client.export_sync("reminders", "csv")
print(f"Exported {result['record_count']} records to {result['file_path']}")

# Async export
job = await client.export_async("reminders", "csv")
print(f"Job created: {job['export_id']}")

# Check status
status = await client.get_job_status(job['export_id'])
print(f"Job status: {status['status']}")

# Download when complete
if status['status'] == 'completed':
    await client.download_job(job['export_id'], "export.csv")
```

### JavaScript Client

```javascript
class DataTransferClient {
  constructor(baseUrl, token) {
    this.baseUrl = baseUrl;
    this.headers = { 'X-Auth-Token': token };
  }

  async exportSync(entityType, format = 'csv') {
    const response = await fetch(
      `${this.baseUrl}/data-transfer/export?execution_mode=sync`,
      {
        method: 'POST',
        headers: { ...this.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_type: entityType, format }),
      }
    );
    return response.json();
  }

  async exportAsync(entityType, format = 'csv') {
    const response = await fetch(
      `${this.baseUrl}/data-transfer/export?execution_mode=async`,
      {
        method: 'POST',
        headers: { ...this.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_type: entityType, format }),
      }
    );
    return response.json();
  }

  async getJobStatus(jobId) {
    const response = await fetch(
      `${this.baseUrl}/data-transfer/jobs/${jobId}`,
      { headers: this.headers }
    );
    return response.json();
  }

  async downloadJob(jobId) {
    const response = await fetch(
      `${this.baseUrl}/data-transfer/jobs/${jobId}/download`,
      { headers: this.headers }
    );
    return response.blob();
  }
}

// Usage
const client = new DataTransferClient('http://localhost:8000/api/v1', 'your-token');

// Async export with polling
const job = await client.exportAsync('reminders', 'csv');
console.log('Job created:', job.export_id);

// Poll for completion
let status;
do {
  await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2s
  status = await client.getJobStatus(job.export_id);
  console.log('Job status:', status.status);
} while (status.status === 'pending' || status.status === 'processing');

// Download
if (status.status === 'completed') {
  const blob = await client.downloadJob(job.export_id);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'export.csv';
  a.click();
}
```

## Best Practices

1. **Use auto mode for unknown data sizes**: Let the system decide sync vs async
2. **Poll job status with backoff**: Don't hammer the API while waiting
3. **Clean up old jobs**: Delete completed jobs after downloading
4. **Grant minimal permissions**: Only give users access to entities they need
5. **Use structured error handling**: Check for specific error types
6. **Log all operations**: Track who exports/imports what
7. **Set rate limits**: Prevent abuse with appropriate limits
8. **Validate file sizes**: Check import file sizes before upload

## Migration from Old System

If you have existing export code:

```python
# Old code (still works - backward compatible)
result = await service.export(request)

# New code with explicit sync mode
result = await service.export(request, execution_mode="sync")

# New code with async mode
result = await service.export(request, execution_mode="async")
```

The default `execution_mode` is `"sync"` for backward compatibility.

## Monitoring

Key metrics to track:

- Export request rate by entity type
- Async vs sync execution ratio
- Job completion rate
- Average job duration
- Permission denial rate
- Failed export/import rate

## Support

For issues or questions:

1. Check logs for detailed error messages
2. Verify user has correct permissions
3. Ensure entity type is supported
4. Check job status endpoint for async exports
5. Review audit logs for operation history
