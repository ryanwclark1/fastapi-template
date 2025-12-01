"""Streaming download operations for storage service.

Provides memory-efficient download operations with:
- Async streaming for large files
- Progress tracking callbacks
- Range request support
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)


async def download_stream(
    client: Any,  # StorageClient
    key: str,
    bucket: str | None = None,
    chunk_size: int = 1024 * 1024,
) -> AsyncIterator[bytes]:
    """Download file as an async byte stream.

    Downloads the file and yields chunks. For true streaming from S3,
    consider implementing range requests.

    Args:
        client: Storage client instance
        key: S3 object key
        bucket: Optional bucket override
        chunk_size: Size of chunks to yield

    Yields:
        Chunks of file data

    Example:
        async for chunk in download_stream(client, "large_file.bin"):
            process_chunk(chunk)
    """
    # Download full file first (S3 doesn't support true streaming without range requests)
    data = await client.download_file(key, bucket)

    # Yield in chunks
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


async def download_to_file(
    client: Any,  # StorageClient
    key: str,
    dest_path: Path,
    bucket: str | None = None,
    chunk_size: int = 1024 * 1024,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download file to local filesystem with progress tracking.

    Args:
        client: Storage client instance
        key: S3 object key
        dest_path: Local path to write file
        bucket: Optional bucket override
        chunk_size: Size of chunks for writing
        on_progress: Callback(bytes_written, total_bytes)

    Returns:
        Path to downloaded file

    Example:
        def progress(written: int, total: int) -> None:
            print(f"Downloaded: {written}/{total}")

        path = await download_to_file(
            client,
            "backups/data.zip",
            Path("/tmp/data.zip"),
            on_progress=progress,
        )
    """
    logger.debug(
        "Downloading file to disk",
        extra={"key": key, "dest": str(dest_path)},
    )

    # Download the file
    data = await client.download_file(key, bucket)
    total_size = len(data)

    # Write to file in chunks with progress
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0
    with open(dest_path, "wb") as f:
        for i in range(0, total_size, chunk_size):
            chunk = data[i : i + chunk_size]
            f.write(chunk)
            bytes_written += len(chunk)
            if on_progress:
                on_progress(bytes_written, total_size)

    logger.debug(
        "File download complete",
        extra={"key": key, "dest": str(dest_path), "size_bytes": total_size},
    )

    return dest_path


async def download_range(
    client: Any,  # StorageClient
    key: str,
    start: int,
    end: int,
    bucket: str | None = None,
) -> bytes:
    """Download a byte range from a file.

    Uses S3 range requests for efficient partial downloads.

    Args:
        client: Storage client instance
        key: S3 object key
        start: Start byte (inclusive)
        end: End byte (inclusive)
        bucket: Optional bucket override

    Returns:
        Bytes in the specified range

    Example:
        # Download first 1MB
        header = await download_range(client, "large.bin", 0, 1024*1024-1)
    """
    await client.ensure_client()

    bucket = bucket or client.settings.bucket

    response = await client._client.get_object(
        Bucket=bucket,
        Key=key,
        Range=f"bytes={start}-{end}",
    )

    async with response["Body"] as stream:
        data = await stream.read()
        return bytes(data) if not isinstance(data, bytes) else data
