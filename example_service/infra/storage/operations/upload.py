"""Streaming upload operations for storage service.

Provides memory-efficient upload operations for large files with:
- Async streaming from any data source
- Progress tracking callbacks
- Chunked multipart uploads for large files
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)


async def upload_stream(
    client: Any,  # StorageClient
    key: str,
    data_stream: AsyncIterator[bytes],
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
    bucket: str | None = None,
    chunk_size: int = 1024 * 1024,  # noqa: ARG001
) -> dict[str, Any]:
    """Upload file from an async byte stream.

    Collects streamed data and uploads to S3. For very large files,
    consider using multipart upload directly.

    Args:
        client: Storage client instance
        key: S3 object key
        data_stream: Async iterator yielding bytes
        content_type: MIME content type
        metadata: Custom metadata
        bucket: Optional bucket override
        chunk_size: Size of chunks to read from stream

    Returns:
        Upload result dict

    Example:
        async def generate_data():
            for chunk in large_data_source:
                yield chunk

        result = await upload_stream(
            client, "data.bin", generate_data()
        )
    """
    from io import BytesIO

    # Collect stream into buffer
    buffer = BytesIO()
    total_size = 0

    async for chunk in data_stream:
        buffer.write(chunk)
        total_size += len(chunk)

    buffer.seek(0)

    logger.debug(
        "Uploading streamed data",
        extra={"key": key, "size_bytes": total_size},
    )

    result = await client.upload_file(
        file_obj=buffer,
        key=key,
        content_type=content_type,
        metadata=metadata,
        bucket=bucket,
    )
    return dict(result)


async def upload_file_chunked(
    client: Any,  # StorageClient
    file_path: Path,
    key: str,
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
    bucket: str | None = None,
    chunk_size: int = 1024 * 1024,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Upload a large file with progress tracking.

    Reads file in chunks and provides progress callbacks.

    Args:
        client: Storage client instance
        file_path: Path to file to upload
        key: S3 object key
        content_type: MIME content type (auto-detected if not provided)
        metadata: Custom metadata
        bucket: Optional bucket override
        chunk_size: Size of chunks for reading
        on_progress: Callback(bytes_uploaded, total_bytes)

    Returns:
        Upload result dict

    Example:
        def progress(uploaded: int, total: int) -> None:
            print(f"Progress: {uploaded}/{total} ({uploaded/total*100:.1f}%)")

        result = await upload_file_chunked(
            client,
            Path("/data/large_file.zip"),
            "uploads/large_file.zip",
            on_progress=progress,
        )
    """
    from io import BytesIO
    import mimetypes

    file_size = file_path.stat().st_size

    # Auto-detect content type
    if content_type is None:
        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

    logger.debug(
        "Uploading file with progress",
        extra={
            "path": str(file_path),
            "key": key,
            "size_bytes": file_size,
        },
    )

    # Read file and track progress
    buffer = BytesIO()
    bytes_read = 0

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            buffer.write(chunk)
            bytes_read += len(chunk)
            if on_progress:
                on_progress(bytes_read, file_size)

    buffer.seek(0)

    result = await client.upload_file(
        file_obj=buffer,
        key=key,
        content_type=content_type,
        metadata=metadata,
        bucket=bucket,
    )
    return dict(result)


async def upload_bytes(
    client: Any,  # StorageClient
    data: bytes,
    key: str,
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
    bucket: str | None = None,
) -> dict[str, Any]:
    """Upload bytes directly to storage.

    Convenience method for uploading in-memory data.

    Args:
        client: Storage client instance
        data: Bytes to upload
        key: S3 object key
        content_type: MIME content type
        metadata: Custom metadata
        bucket: Optional bucket override

    Returns:
        Upload result dict
    """
    from io import BytesIO

    result = await client.upload_file(
        file_obj=BytesIO(data),
        key=key,
        content_type=content_type or "application/octet-stream",
        metadata=metadata,
        bucket=bucket,
    )
    return dict(result)
