"""Storage metrics for Prometheus monitoring.

This module provides comprehensive metrics for monitoring storage operations including:
- Operation counters and timing (upload, download, delete, copy, move, list)
- File size distribution tracking
- Batch operation metrics
- Active connection monitoring
- Error tracking by type
- Presigned URL generation tracking
- Client lifecycle metrics

All metrics are registered with the shared REGISTRY from the prometheus module
to ensure they are exposed via the /metrics endpoint.

Usage:
    from example_service.infra.storage.metrics import (
        record_operation_success,
        record_operation_error,
        record_batch_operation,
        storage_connections_active,
    )

    # Record a successful upload
    record_operation_success("upload", duration_seconds=1.5, size_bytes=1048576)

    # Record a failed download
    record_operation_error("download", "StorageTimeoutError", duration_seconds=5.0)

    # Track active connections
    with storage_connections_active.track_inprogress():
        # Perform storage operation
        pass
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from example_service.infra.metrics.prometheus import REGISTRY

# Bucket configurations for storage-specific metrics

# Storage operations typically take longer than HTTP requests
# Covers latency from 10ms to 30s for network operations
STORAGE_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# File size buckets from 1KB to 100MB
# Covers common file sizes for uploads/downloads
STORAGE_SIZE_BUCKETS = (1024, 10240, 102400, 1048576, 10485760, 52428800, 104857600)  # 1KB to 100MB

# Batch operation size buckets
# Tracks number of files in batch operations
BATCH_SIZE_BUCKETS = (1, 5, 10, 25, 50, 100, 250, 500)

# Operation counters
storage_operations_total = Counter(
    "storage_operations_total",
    "Total storage operations",
    [
        "operation",
        "status",
    ],  # operation: upload/download/delete/copy/move/list, status: success/error
    registry=REGISTRY,
)

# Operation duration histogram
storage_operation_duration_seconds = Histogram(
    "storage_operation_duration_seconds",
    "Storage operation duration in seconds",
    ["operation"],
    buckets=STORAGE_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# File size distribution
storage_file_size_bytes = Histogram(
    "storage_file_size_bytes",
    "Size of files uploaded/downloaded in bytes",
    ["operation"],
    buckets=STORAGE_SIZE_BUCKETS,
    registry=REGISTRY,
)

# Batch operation metrics
storage_batch_size = Histogram(
    "storage_batch_size",
    "Number of files in batch operations",
    ["operation"],  # batch_upload/batch_download/batch_delete
    buckets=BATCH_SIZE_BUCKETS,
    registry=REGISTRY,
)

storage_batch_success_count = Counter(
    "storage_batch_success_count",
    "Number of files successfully processed in batch operations",
    ["operation"],
    registry=REGISTRY,
)

storage_batch_failure_count = Counter(
    "storage_batch_failure_count",
    "Number of files that failed in batch operations",
    ["operation"],
    registry=REGISTRY,
)

# Active connections gauge
storage_connections_active = Gauge(
    "storage_connections_active",
    "Number of active storage connections/operations",
    registry=REGISTRY,
)

# Error tracking by type
storage_errors_total = Counter(
    "storage_errors_total",
    "Storage operation errors by type",
    ["operation", "error_type"],  # error_type: StorageTimeoutError, StoragePermissionError, etc.
    registry=REGISTRY,
)

# Presigned URL metrics
storage_presigned_urls_generated = Counter(
    "storage_presigned_urls_generated",
    "Total presigned URLs generated",
    ["type"],  # download/upload
    registry=REGISTRY,
)

# Client lifecycle metrics
storage_client_initializations = Counter(
    "storage_client_initializations",
    "Number of storage client initializations",
    ["status"],  # success/error
    registry=REGISTRY,
)


def record_operation_success(
    operation: str,
    duration_seconds: float,
    size_bytes: int | None = None,
) -> None:
    """Record a successful storage operation.

    Args:
        operation: The operation type (e.g., 'upload', 'download', 'delete')
        duration_seconds: Operation duration in seconds
        size_bytes: Optional file size in bytes for upload/download operations

    Example:
        >>> record_operation_success("upload", 1.5, size_bytes=1048576)
        >>> record_operation_success("delete", 0.2)
    """
    storage_operations_total.labels(operation=operation, status="success").inc()
    storage_operation_duration_seconds.labels(operation=operation).observe(duration_seconds)
    if size_bytes is not None:
        storage_file_size_bytes.labels(operation=operation).observe(size_bytes)


def record_operation_error(
    operation: str,
    error_type: str,
    duration_seconds: float,
) -> None:
    """Record a failed storage operation.

    Args:
        operation: The operation type (e.g., 'upload', 'download', 'delete')
        error_type: The error type/class name (e.g., 'StorageTimeoutError')
        duration_seconds: Operation duration in seconds before failure

    Example:
        >>> record_operation_error("download", "StorageTimeoutError", 5.0)
        >>> record_operation_error("upload", "StoragePermissionError", 0.5)
    """
    storage_operations_total.labels(operation=operation, status="error").inc()
    storage_operation_duration_seconds.labels(operation=operation).observe(duration_seconds)
    storage_errors_total.labels(operation=operation, error_type=error_type).inc()


def record_batch_operation(
    operation: str,
    total_count: int,
    success_count: int,
    failure_count: int,
) -> None:
    """Record batch operation metrics.

    Args:
        operation: The batch operation type (e.g., 'batch_upload', 'batch_delete')
        total_count: Total number of files in the batch
        success_count: Number of files successfully processed
        failure_count: Number of files that failed

    Example:
        >>> record_batch_operation(
        ...     "batch_upload",
        ...     total_count=100,
        ...     success_count=98,
        ...     failure_count=2,
        ... )
    """
    storage_batch_size.labels(operation=operation).observe(total_count)
    storage_batch_success_count.labels(operation=operation).inc(success_count)
    storage_batch_failure_count.labels(operation=operation).inc(failure_count)
