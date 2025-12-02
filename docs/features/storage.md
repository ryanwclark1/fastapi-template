# Storage System

## Overview

The storage system provides a robust, multi-backend abstraction layer for managing object storage in the application. It supports multiple cloud storage providers (S3, MinIO, with future support for GCS and Azure Blob) through a unified interface, enabling seamless switching between providers without code changes.

### Key Features

- **Multi-Backend Support**: Single interface for S3, MinIO, GCS (future), Azure (future)
- **Multi-Tenant Isolation**: Per-tenant buckets with configurable naming patterns
- **Bucket Management**: Create, delete, list, and manage storage buckets
- **ACL Support**: Fine-grained access control on objects and buckets
- **Async-First**: Fully asynchronous operations with connection pooling
- **Observability**: Built-in metrics, tracing, and structured logging
- **Presigned URLs**: Generate secure upload/download URLs for client-side operations
- **Streaming**: Efficient handling of large files with streaming support
- **Type-Safe**: Full type hints with Protocol-based abstractions

## Architecture

### Protocol-Based Backend System

The storage system uses Python's `typing.Protocol` for structural typing, allowing flexible backend implementations without forced inheritance:

```
StorageService (orchestration, observability)
       ↓
Backend Factory (creates appropriate backend)
       ↓
StorageBackend Protocol (abstract interface)
       ↓
    ┌──┴───────────────┐
    │                  │
S3Backend          GCSBackend (future)
```

### Multi-Tenancy Architecture

The system supports **bucket-per-tenant** isolation strategy:

1. **Tenant Buckets**: Each tenant gets dedicated bucket(s)
   - Naming pattern: `{tenant_slug}-uploads` (configurable)
   - Full isolation at storage layer
   - Easy cost tracking and quota management

2. **Shared Staging Bucket**: `staging-uploads` (configurable)
   - Temporary storage before tenant assignment
   - Batch import operations
   - Anonymous uploads pending tenant association

3. **Bucket Resolution Priority**:
   - Explicit bucket parameter (highest priority)
   - Tenant bucket (if multi-tenancy enabled and tenant context provided)
   - Shared bucket or default bucket (fallback)

### Tenant Context Flow

```
Request → JWT Validation → AuthUser
           ↓
     Extract tenant_uuid/tenant_slug from metadata
           ↓
     Resolve bucket: {tenant_slug}-uploads
           ↓
     StorageService uses tenant bucket
```

## Configuration

### Environment Variables

#### Basic Configuration

```bash
# Enable storage
STORAGE_ENABLED=true

# Backend selection
STORAGE_BACKEND=s3  # Options: s3, minio, gcs (future), azure (future)

# Default bucket
STORAGE_BUCKET=my-app-uploads

# AWS S3 Configuration
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
STORAGE_S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG

# Optional: Custom endpoint (for MinIO or S3-compatible services)
STORAGE_S3_ENDPOINT=https://s3.amazonaws.com
```

#### MinIO Configuration (Development)

```bash
STORAGE_ENABLED=true
STORAGE_BACKEND=minio
STORAGE_BUCKET=dev-uploads

STORAGE_S3_ENDPOINT=http://localhost:9000
STORAGE_S3_ACCESS_KEY=minioadmin
STORAGE_S3_SECRET_KEY=minioadmin
STORAGE_S3_USE_SSL=false
STORAGE_S3_VERIFY_SSL=false
```

#### Multi-Tenancy Configuration

```bash
# Enable multi-tenant storage isolation
STORAGE_ENABLE_MULTI_TENANCY=true

# Bucket naming pattern (supports {tenant_uuid} and {tenant_slug})
STORAGE_BUCKET_NAMING_PATTERN={tenant_slug}-uploads

# Shared staging bucket for pre-tenant-assignment data
STORAGE_SHARED_BUCKET=staging-uploads

# Require tenant context (fail if missing)
STORAGE_REQUIRE_TENANT_CONTEXT=false
```

#### ACL and Storage Class Defaults

```bash
# Default ACL for uploads (options: private, public-read, public-read-write, etc.)
STORAGE_DEFAULT_ACL=private

# Default storage class (options: STANDARD, REDUCED_REDUNDANCY, GLACIER, etc.)
STORAGE_DEFAULT_STORAGE_CLASS=STANDARD
```

#### Advanced Configuration

```bash
# Connection pooling
STORAGE_MAX_POOL_CONNECTIONS=10

# Retry configuration
STORAGE_MAX_RETRIES=3
STORAGE_RETRY_MODE=adaptive  # Options: adaptive, standard, legacy

# Timeouts
STORAGE_TIMEOUT=60

# Health checks
STORAGE_HEALTH_CHECK_ENABLED=true
STORAGE_HEALTH_CHECK_TIMEOUT=5
```

### Configuration Examples

#### Example 1: Single-Tenant S3 (Production)

```bash
# Basic S3 setup for single-tenant application
STORAGE_ENABLED=true
STORAGE_BACKEND=s3
STORAGE_BUCKET=acme-app-uploads
STORAGE_S3_REGION=us-west-2
STORAGE_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
STORAGE_S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG
STORAGE_DEFAULT_ACL=private
```

#### Example 2: Multi-Tenant S3 (SaaS)

```bash
# Multi-tenant SaaS with per-tenant buckets
STORAGE_ENABLED=true
STORAGE_BACKEND=s3
STORAGE_S3_REGION=us-west-2
STORAGE_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
STORAGE_S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG

# Multi-tenancy settings
STORAGE_ENABLE_MULTI_TENANCY=true
STORAGE_BUCKET_NAMING_PATTERN={tenant_slug}-uploads
STORAGE_SHARED_BUCKET=staging-uploads
STORAGE_DEFAULT_ACL=private
```

#### Example 3: MinIO (Local Development)

```bash
# Local development with MinIO
STORAGE_ENABLED=true
STORAGE_BACKEND=minio
STORAGE_BUCKET=dev-uploads
STORAGE_S3_ENDPOINT=http://localhost:9000
STORAGE_S3_ACCESS_KEY=minioadmin
STORAGE_S3_SECRET_KEY=minioadmin
STORAGE_S3_USE_SSL=false
STORAGE_S3_VERIFY_SSL=false

# Optional: Enable multi-tenancy locally
STORAGE_ENABLE_MULTI_TENANCY=true
STORAGE_BUCKET_NAMING_PATTERN={tenant_slug}-dev-uploads
STORAGE_SHARED_BUCKET=dev-staging
```

## API Usage

The storage system provides two API layers:

1. **`/api/v1/storage/`** - Admin-level raw storage operations (bucket management, object operations)
2. **`/api/v1/files/`** - User-level tracked file operations (with database records)

### Storage API Endpoints (Admin)

#### Bucket Management

**Create Bucket**
```bash
POST /api/v1/storage/buckets
Content-Type: application/json

{
  "name": "acme-uploads",
  "region": "us-west-2",
  "acl": "private",
  "tenant_uuid": "abc-123-def"
}
```

**List Buckets**
```bash
GET /api/v1/storage/buckets

# Response:
{
  "buckets": [
    {
      "name": "acme-uploads",
      "region": "us-west-2",
      "creation_date": "2025-01-15T10:30:00Z",
      "versioning_enabled": false,
      "tenant_uuid": "abc-123-def"
    }
  ],
  "total": 1
}
```

**Delete Bucket**
```bash
DELETE /api/v1/storage/buckets/acme-uploads?force=false
```

**Get Bucket Info**
```bash
GET /api/v1/storage/buckets/acme-uploads
```

#### Object Operations

**Upload Object**
```bash
POST /api/v1/storage/objects/uploads/document.pdf
Content-Type: multipart/form-data

file: <binary data>
bucket: acme-uploads (optional)
acl: private (optional)
storage_class: STANDARD (optional)
```

**List Objects**
```bash
GET /api/v1/storage/objects?prefix=uploads/&max_keys=100&bucket=acme-uploads
```

**Download Object**
```bash
GET /api/v1/storage/objects/uploads/document.pdf?bucket=acme-uploads
```

**Delete Object**
```bash
DELETE /api/v1/storage/objects/uploads/document.pdf?bucket=acme-uploads
```

#### ACL Management

**Set Object ACL**
```bash
PUT /api/v1/storage/objects/uploads/document.pdf/acl
Content-Type: application/json

{
  "acl": "public-read"
}
```

**Get Object ACL**
```bash
GET /api/v1/storage/objects/uploads/document.pdf/acl

# Response:
{
  "owner": {
    "display_name": "owner",
    "id": "abc123"
  },
  "grants": [...]
}
```

### Files API Endpoints (User)

The Files API automatically handles tenant context extraction and bucket resolution:

**Upload File (Direct)**
```bash
POST /api/v1/files/upload
Content-Type: multipart/form-data
Authorization: Bearer <jwt-token-with-tenant-metadata>

file: <binary data>
owner_id: user-123 (optional)
is_public: false (optional)
```

The tenant context is automatically extracted from the JWT token and the file is uploaded to the tenant's bucket.

**Upload File (Presigned)**
```bash
# Step 1: Request presigned upload URL
POST /api/v1/files/presigned-upload
Authorization: Bearer <jwt-token-with-tenant-metadata>

{
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size_bytes": 1024000,
  "is_public": false
}

# Response:
{
  "upload_url": "https://s3.amazonaws.com/...",
  "upload_fields": {...},
  "file_id": "uuid",
  "expires_in": 3600
}

# Step 2: Upload directly to S3 from browser
# (using presigned URL)

# Step 3: Notify completion
POST /api/v1/files/{file_id}/complete
Authorization: Bearer <jwt-token>
```

## CLI Usage

The storage CLI provides comprehensive commands for bucket management and file operations.

### Bucket Management

**List Buckets**
```bash
example-service storage buckets list
```

**Create Bucket**
```bash
# Basic bucket
example-service storage buckets create my-bucket

# With region and ACL
example-service storage buckets create my-bucket --region us-west-2 --acl private
```

**Delete Bucket**
```bash
# Safe delete (requires confirmation)
example-service storage buckets delete my-bucket --confirm

# Force delete (non-empty bucket)
example-service storage buckets delete my-bucket --force --confirm
```

**Get Bucket Info**
```bash
example-service storage buckets info my-bucket
```

### File Operations

**Upload Files**
```bash
# Single file with ACL
example-service storage upload local_file.pdf --key uploads/file.pdf --acl public-read

# Single file with storage class
example-service storage upload large_file.zip --key archives/file.zip --storage-class GLACIER

# Multiple files
example-service storage upload file1.pdf file2.pdf --prefix uploads/

# Recursive directory upload
example-service storage upload ./documents/ --prefix uploads/docs/ --recursive

# With tenant specification (for multi-tenant setups)
TENANT_ID=acme-123 example-service storage upload file.pdf --key uploads/file.pdf
```

**Download Files**
```bash
# Single file
example-service storage download uploads/file.pdf --output ./local_file.pdf

# Multiple files
example-service storage download uploads/file1.pdf uploads/file2.pdf --output ./downloads/

# Download with specific bucket
example-service storage download uploads/file.pdf --bucket my-bucket --output ./file.pdf
```

**List Files**
```bash
# List all files
example-service storage list

# List with prefix filter
example-service storage list uploads/2024/

# List with limit
example-service storage list --limit 50 uploads/
```

**Copy Files**
```bash
# Copy within same bucket
example-service storage copy uploads/source.pdf uploads/dest.pdf

# Copy to different bucket with ACL
example-service storage copy uploads/file.pdf --to-bucket archive --to-key archives/file.pdf --acl private
```

**Move Files**
```bash
# Move/rename file
example-service storage move uploads/old_name.pdf uploads/new_name.pdf

# Move to different prefix with ACL
example-service storage move uploads/temp/file.pdf uploads/permanent/file.pdf --acl private
```

**Delete Files**
```bash
# Dry run (preview)
example-service storage delete uploads/old/

# Actually delete (requires confirmation)
example-service storage delete uploads/old/ --prefix --confirm

# Delete specific files
example-service storage delete uploads/file1.pdf uploads/file2.pdf --confirm
```

**Check Storage Status**
```bash
# Health check
example-service storage check

# Configuration info
example-service storage info
```

## Python API Usage

### Direct Storage Service Usage

```python
from example_service.infra.storage import get_storage_service
from example_service.infra.storage.backends.protocol import TenantContext

async def upload_example():
    # Get storage service
    storage = get_storage_service()
    await storage.startup()

    try:
        # Create tenant context
        tenant = TenantContext(
            tenant_uuid="abc-123",
            tenant_slug="acme",
            metadata={}
        )

        # Upload with tenant context and ACL
        with open("document.pdf", "rb") as f:
            result = await storage.upload_file(
                file_obj=f,
                key="documents/report.pdf",
                content_type="application/pdf",
                acl="private",
                storage_class="STANDARD",
                tenant_context=tenant
            )

        print(f"Uploaded to: {result['bucket']}/{result['key']}")
        print(f"ETag: {result['etag']}")

    finally:
        await storage.shutdown()
```

### Using Files Service (Recommended)

```python
from example_service.features.files.service import FileService
from example_service.infra.storage.backends.protocol import TenantContext

async def tracked_upload_example(session):
    # Get file service
    file_service = FileService(session=session)

    # Create tenant context
    tenant = TenantContext(
        tenant_uuid="abc-123",
        tenant_slug="acme",
        metadata={}
    )

    # Upload tracked file (creates database record)
    with open("document.pdf", "rb") as f:
        file_record = await file_service.upload_file(
            file_obj=f,
            filename="report.pdf",
            content_type="application/pdf",
            owner_id="user-123",
            is_public=False,
            acl="private",  # Optional: explicit ACL
            tenant_context=tenant
        )

    print(f"File ID: {file_record.id}")
    print(f"Storage Key: {file_record.storage_key}")
    print(f"Bucket: {file_record.bucket}")
```

### Bucket Management

```python
async def bucket_operations():
    storage = get_storage_service()
    await storage.startup()

    try:
        # Create bucket
        await storage.create_bucket(
            bucket="acme-uploads",
            region="us-west-2",
            acl="private"
        )

        # List buckets
        buckets = await storage.list_buckets()
        for bucket in buckets:
            print(f"Bucket: {bucket['name']}, Region: {bucket['region']}")

        # Check if bucket exists
        exists = await storage.bucket_exists("acme-uploads")

        # Delete bucket
        await storage.delete_bucket("acme-uploads", force=False)

    finally:
        await storage.shutdown()
```

### ACL Management

```python
async def acl_operations():
    storage = get_storage_service()
    await storage.startup()

    try:
        # Upload with ACL
        with open("public_file.pdf", "rb") as f:
            result = await storage.upload_file(
                file_obj=f,
                key="public/document.pdf",
                acl="public-read"
            )

        # Set ACL on existing object
        await storage.set_object_acl(
            key="public/document.pdf",
            acl="private"
        )

        # Get object ACL
        acl_info = await storage.get_object_acl("public/document.pdf")
        print(f"Owner: {acl_info['owner']}")

    finally:
        await storage.shutdown()
```

## Multi-Tenancy Guide

### Tenant Context Extraction

The system supports two methods for tenant identification:

#### 1. JWT Metadata (Primary)

Add tenant information to JWT claims:

```python
# In accent-auth or your auth provider
token_metadata = {
    "tenant_uuid": "abc-123-def",
    "tenant_slug": "acme",
    # ... other metadata
}
```

The `TenantContextDep` dependency automatically extracts this:

```python
from example_service.core.dependencies.tenant import TenantContextDep

@router.post("/upload")
async def upload_file(
    file: UploadFile,
    tenant_context: TenantContextDep = None
):
    # tenant_context is automatically populated from JWT
    # Files go to {tenant_slug}-uploads bucket
    ...
```

#### 2. Custom Header (Fallback)

For service-to-service calls or CLI operations:

```bash
curl -X POST https://api.example.com/api/v1/storage/objects/document.pdf \
  -H "X-Tenant-ID: acme-123" \
  -F "file=@document.pdf"
```

### Bucket Provisioning Workflow

1. **Tenant Onboarding**: When a new tenant signs up
2. **Create Tenant Bucket**: Admin calls bucket creation API
3. **Track Association**: Store tenant-bucket mapping in database (optional)
4. **Automatic Resolution**: Subsequent uploads automatically use tenant bucket

```python
# Admin endpoint for tenant provisioning
@router.post("/admin/tenants/{tenant_id}/provision-storage")
async def provision_tenant_storage(tenant_id: str, tenant_slug: str):
    storage = get_storage_service()

    # Create tenant bucket
    bucket_name = f"{tenant_slug}-uploads"
    await storage.create_bucket(
        bucket=bucket_name,
        region="us-west-2",
        acl="private"
    )

    # Store tenant-bucket association in database
    # ... (optional)

    return {"bucket": bucket_name, "status": "provisioned"}
```

### Migration from Single-Tenant to Multi-Tenant

**Phase 1**: Deploy with `enable_multi_tenancy=false` (existing behavior)

```bash
STORAGE_ENABLE_MULTI_TENANCY=false
STORAGE_BUCKET=shared-uploads
```

**Phase 2**: Create tenant buckets for all existing tenants

```python
async def migrate_to_multitenant():
    tenants = await get_all_tenants()
    storage = get_storage_service()

    for tenant in tenants:
        bucket_name = f"{tenant.slug}-uploads"
        await storage.create_bucket(bucket_name)
```

**Phase 3**: Enable multi-tenancy

```bash
STORAGE_ENABLE_MULTI_TENANCY=true
STORAGE_BUCKET_NAMING_PATTERN={tenant_slug}-uploads
STORAGE_SHARED_BUCKET=shared-uploads  # Fallback
```

**Phase 4** (Optional): Migrate existing files to tenant buckets

```python
async def migrate_files_to_tenant_buckets():
    files = await get_all_files()
    storage = get_storage_service()

    for file in files:
        tenant = await get_file_tenant(file)
        if tenant:
            # Copy to tenant bucket
            source_bucket = "shared-uploads"
            dest_bucket = f"{tenant.slug}-uploads"

            # Download from shared
            data = await storage.download_file(file.storage_key, source_bucket)

            # Upload to tenant bucket
            await storage.upload_file(
                BytesIO(data),
                key=file.storage_key,
                bucket=dest_bucket,
                tenant_context=TenantContext(
                    tenant_uuid=tenant.id,
                    tenant_slug=tenant.slug
                )
            )

            # Update file record
            file.bucket = dest_bucket
            await session.commit()
```

## Best Practices

### Security

1. **Use Private ACL by Default**: Only make files public when necessary
2. **Enable Multi-Tenancy**: For SaaS applications, always enable tenant isolation
3. **Rotate Credentials**: Regularly rotate S3 access keys
4. **Use IAM Roles**: In production, prefer IAM roles over access keys
5. **Enable Versioning**: Protect against accidental deletions

### Performance

1. **Use Presigned URLs**: For large files, use client-side uploads with presigned URLs
2. **Enable Streaming**: For large downloads, use streaming responses
3. **Connection Pooling**: Tune `STORAGE_MAX_POOL_CONNECTIONS` based on load
4. **Regional Buckets**: Create buckets in the same region as your application

### Operations

1. **Monitor Metrics**: Track `storage_operations_total`, `storage_errors_total`
2. **Set Up Alerts**: Alert on high error rates or slow operations
3. **Lifecycle Policies**: Configure S3 lifecycle rules for cost optimization
4. **Backup Strategy**: Implement cross-region replication for critical data

### Cost Optimization

1. **Use Storage Classes**: Move infrequently accessed data to `GLACIER` or `DEEP_ARCHIVE`
2. **Implement Expiration**: Set expiration policies on temporary files
3. **Monitor Usage**: Track per-tenant storage costs with bucket-level metrics
4. **Compress Data**: Compress files before upload when appropriate

## Troubleshooting

### Storage Not Configured

**Error**: `StorageNotConfiguredError: Storage service is not available`

**Solution**: Check that `STORAGE_ENABLED=true` and credentials are set:

```bash
example-service storage info
example-service storage check
```

### Connection Timeout

**Error**: `ReadTimeoutError` or `ConnectTimeoutError`

**Solution**: Increase timeout settings:

```bash
STORAGE_TIMEOUT=120
STORAGE_MAX_RETRIES=5
```

### Bucket Not Found

**Error**: `NoSuchBucket` or `StorageFileNotFoundError`

**Solution**:
- Verify bucket exists: `example-service storage buckets list`
- Check multi-tenancy config: ensure tenant bucket is created
- Create bucket: `example-service storage buckets create <name>`

### ACL Errors

**Error**: `AccessDenied` when setting ACL

**Solution**: Verify S3 permissions allow ACL operations:
- Ensure IAM policy includes `s3:PutObjectAcl` and `s3:GetObjectAcl`
- Check bucket ACL settings allow ACL modifications

### Multi-Tenancy Issues

**Error**: Files going to wrong bucket

**Solution**:
- Verify JWT includes `tenant_uuid` and `tenant_slug` in metadata
- Check tenant context extraction: add logging to `TenantContextDep`
- Verify `STORAGE_BUCKET_NAMING_PATTERN` is correct

## Metrics and Monitoring

### Key Metrics

- `storage_operations_total{operation, status, backend, tenant}` - Total operations by type
- `storage_errors_total{operation, backend, tenant}` - Error count by operation
- `storage_operation_duration_seconds{operation, backend, tenant}` - Operation latency
- `storage_upload_bytes_total{backend, tenant}` - Total bytes uploaded
- `storage_download_bytes_total{backend, tenant}` - Total bytes downloaded
- `storage_bucket_operations_total{operation, status}` - Bucket operations
- `storage_acl_operations_total{operation, status}` - ACL operations

### Example Prometheus Queries

```promql
# Upload success rate
rate(storage_operations_total{operation="upload",status="success"}[5m])
/
rate(storage_operations_total{operation="upload"}[5m])

# P95 upload latency by tenant
histogram_quantile(0.95,
  rate(storage_operation_duration_seconds_bucket{operation="upload"}[5m])
) by (tenant)

# Storage usage by tenant
sum by (tenant) (storage_upload_bytes_total)
- sum by (tenant) (storage_download_bytes_total)
```

## References

- [AWS S3 API Documentation](https://docs.aws.amazon.com/s3/)
- [MinIO Documentation](https://min.io/docs/)
- [S3 ACL Overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/acl-overview.html)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)

## Related Documentation

- [Files Feature](./accent-ai-features.md#file-management) - User-level file tracking
- [Health Checks](./health-checks.md) - Storage health monitoring
- [Database Guide](../database/database-guide.md) - File metadata storage
- [Architecture Overview](../architecture/overview.md) - System design patterns
