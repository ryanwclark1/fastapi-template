"""Storage operation instrumentation with OpenTelemetry and Prometheus metrics.

Provides unified observability for storage operations through:
- OpenTelemetry spans with detailed attributes
- Prometheus metrics for operation tracking
- Context managers for automatic cleanup and error handling
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from example_service.infra.tracing.opentelemetry import get_tracer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Module-level tracer
_tracer = get_tracer("storage")


@asynccontextmanager
async def track_storage_operation(
    operation: str,
    key: str | None = None,
    bucket: str | None = None,
    size_bytes: int | None = None,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Track a storage operation with OpenTelemetry spans and Prometheus metrics.

    Creates an OpenTelemetry span and records Prometheus metrics for the operation.
    The context dict can be updated by the caller to add additional attributes
    that will be recorded when the span ends (e.g., result size, checksum).

    Args:
        operation: Operation name (upload, download, delete, copy, move, list)
        key: S3 object key
        bucket: S3 bucket name
        size_bytes: File size in bytes (for uploads)
        content_type: MIME content type
        metadata: Additional metadata to include in span

    Yields:
        A context dictionary that can be updated with additional attributes

    Example:
        async with track_storage_operation("upload", key="path/to/file.txt") as ctx:
            result = await client.upload_file(...)
            ctx["result_size"] = result["size_bytes"]
            ctx["checksum"] = result["checksum_sha256"]
    """
    from . import metrics

    start_time = time.perf_counter()
    context: dict[str, Any] = {}

    # Build span attributes
    span_attributes: dict[str, Any] = {
        "storage.operation": operation,
    }
    if key:
        span_attributes["storage.key"] = key
    if bucket:
        span_attributes["storage.bucket"] = bucket
    if size_bytes is not None:
        span_attributes["storage.size_bytes"] = size_bytes
    if content_type:
        span_attributes["storage.content_type"] = content_type
    if metadata:
        for k, v in metadata.items():
            span_attributes[f"storage.metadata.{k}"] = str(v)

    # Increment active connections
    metrics.storage_connections_active.inc()

    with _tracer.start_as_current_span(
        f"storage.{operation}",
        attributes=span_attributes,
    ) as span:
        try:
            yield context

            # Record success
            duration = time.perf_counter() - start_time

            # Add any context updates to span
            for k, v in context.items():
                span.set_attribute(f"storage.result.{k}", str(v))

            # Get final size (from context if provided, otherwise from input)
            final_size = context.get("result_size", size_bytes)

            metrics.record_operation_success(
                operation=operation,
                duration_seconds=duration,
                size_bytes=final_size,
            )

            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            # Record error
            duration = time.perf_counter() - start_time
            error_type = type(e).__name__

            metrics.record_operation_error(
                operation=operation,
                error_type=error_type,
                duration_seconds=duration,
            )

            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

        finally:
            metrics.storage_connections_active.dec()


def create_storage_span(
    operation: str,
    key: str | None = None,
    bucket: str | None = None,
    **attributes: Any,
) -> trace.Span:
    """Create a storage operation span for manual lifecycle management.

    Use this when you need more control over span lifecycle than the
    context manager provides.

    Args:
        operation: Operation name
        key: S3 object key
        bucket: S3 bucket name
        **attributes: Additional span attributes

    Returns:
        OpenTelemetry span (caller must call span.end())

    Example:
        span = create_storage_span("batch_upload", bucket="my-bucket")
        try:
            for file in files:
                # Process file
                span.add_event("file_uploaded", {"key": file.key})
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
        finally:
            span.end()
    """
    span_attributes: dict[str, Any] = {
        "storage.operation": operation,
    }
    if key:
        span_attributes["storage.key"] = key
    if bucket:
        span_attributes["storage.bucket"] = bucket
    span_attributes.update(attributes)

    return _tracer.start_span(
        f"storage.{operation}",
        attributes=span_attributes,
    )


def add_storage_event(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Add an event to the current storage span.

    Useful for marking significant points within a storage operation.

    Args:
        name: Event name
        attributes: Event attributes
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(name, attributes=attributes or {})
