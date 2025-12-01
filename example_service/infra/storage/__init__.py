"""Storage infrastructure for S3/MinIO object storage.

This module provides a comprehensive storage layer with:
- StorageService with singleton pattern and full observability
- Streaming operations for memory-efficient large file handling
- Batch operations with concurrency control and progress tracking
- Presigned URL generation for browser uploads/downloads
- FastAPI dependencies for easy route integration
- Health check provider for monitoring
- Prometheus metrics and OpenTelemetry instrumentation

Quick Start:
    # In routes using dependency injection (recommended)
    from example_service.infra.storage import Storage

    @router.post("/upload")
    async def upload(file: UploadFile, storage: Storage):
        result = await storage.upload_file(file.file, key="path/file.txt")
        return result

    # Direct service access for background tasks
    from example_service.infra.storage import get_storage_service

    service = get_storage_service()
    await service.startup()
    result = await service.upload_file(file, key="path/file.txt")

    # Advanced: Streaming large files
    from example_service.infra.storage import upload_stream

    async with upload_stream(service, key="large-file.bin") as stream:
        async for chunk in file_chunks:
            await stream.write(chunk)
"""

from __future__ import annotations

# Core settings
from example_service.core.settings.storage import StorageSettings

# FastAPI dependencies
from .dependencies import (
    OptionalStorage,
    Storage,
    optional_storage,
    require_storage,
)

# Exceptions
from .exceptions import (
    StorageDownloadError,
    StorageError,
    StorageFileNotFoundError,
    StorageNotConfiguredError,
    StoragePermissionError,
    StorageQuotaExceededError,
    StorageTimeoutError,
    StorageUploadError,
    StorageValidationError,
)

# Instrumentation (for advanced usage)
from .instrumentation import (
    add_storage_event,
    create_storage_span,
    track_storage_operation,
)

# Metrics (for advanced usage)
from .metrics import (
    record_batch_operation,
    record_operation_error,
    record_operation_success,
    storage_connections_active,
    storage_errors_total,
    storage_file_size_bytes,
    storage_operation_duration_seconds,
    storage_operations_total,
)

# Operations
from .operations import (
    # Batch
    BatchResult,
    BatchUploadItem,
    # Presigned
    PresignedDownloadUrl,
    PresignedUploadUrl,
    batch_delete,
    batch_download,
    batch_upload,
    # Streaming - Download
    download_range,
    download_stream,
    download_to_file,
    generate_bulk_download_urls,
    generate_download_url,
    generate_upload_url,
    # Streaming - Upload
    upload_bytes,
    upload_file_chunked,
    upload_stream,
)

# Path utilities
from .path import (
    generate_temp_path,
    generate_thumbnail_path,
    generate_unique_key,
    generate_upload_path,
    get_file_extension,
    is_image_content_type,
    parse_upload_path,
    sanitize_filename,
    sanitize_path_component,
    validate_path,
)

# Core service
from .service import StorageService, get_storage_service, reset_storage_service

__all__ = [
    # Core service
    "StorageService",
    "StorageSettings",
    "get_storage_service",
    "reset_storage_service",
    # FastAPI Dependencies
    "Storage",
    "OptionalStorage",
    "require_storage",
    "optional_storage",
    # Exceptions
    "StorageError",
    "StorageNotConfiguredError",
    "StorageFileNotFoundError",
    "StorageUploadError",
    "StorageDownloadError",
    "StoragePermissionError",
    "StorageQuotaExceededError",
    "StorageValidationError",
    "StorageTimeoutError",
    # Path utilities
    "generate_upload_path",
    "generate_thumbnail_path",
    "generate_temp_path",
    "sanitize_filename",
    "sanitize_path_component",
    "validate_path",
    "parse_upload_path",
    "get_file_extension",
    "is_image_content_type",
    "generate_unique_key",
    # Metrics (advanced usage)
    "storage_operations_total",
    "storage_operation_duration_seconds",
    "storage_file_size_bytes",
    "storage_connections_active",
    "storage_errors_total",
    "record_operation_success",
    "record_operation_error",
    "record_batch_operation",
    # Instrumentation (advanced usage)
    "track_storage_operation",
    "create_storage_span",
    "add_storage_event",
    # Streaming operations - Upload
    "upload_stream",
    "upload_file_chunked",
    "upload_bytes",
    # Streaming operations - Download
    "download_stream",
    "download_to_file",
    "download_range",
    # Batch operations
    "BatchResult",
    "BatchUploadItem",
    "batch_upload",
    "batch_download",
    "batch_delete",
    # Presigned URLs
    "PresignedDownloadUrl",
    "PresignedUploadUrl",
    "generate_download_url",
    "generate_upload_url",
    "generate_bulk_download_urls",
]
