"""Enhanced batch operations for storage service.

Provides batch upload, download, and delete operations with:
- Concurrency control via semaphores
- Per-file progress tracking
- Comprehensive result reporting
- Retry logic for transient failures
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a batch operation."""

    total: int
    successful: int
    failed: int
    results: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total == 0:
            return 100.0
        return (self.successful / self.total) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": round(self.success_rate, 2),
            "duration_seconds": round(self.duration_seconds, 3),
            "results": self.results,
        }


@dataclass
class BatchUploadItem:
    """Item for batch upload operations."""

    key: str
    data: BinaryIO | bytes
    content_type: str = "application/octet-stream"
    metadata: dict[str, str] | None = None


async def batch_upload(
    client: Any,  # StorageClient
    items: list[BatchUploadItem],
    max_concurrency: int = 5,
    on_progress: Callable[[str, bool, str | None], None] | None = None,
    retry_count: int = 1,
) -> BatchResult:
    """Upload multiple files with enhanced tracking.

    Args:
        client: Storage client instance
        items: List of BatchUploadItem objects
        max_concurrency: Maximum concurrent uploads
        on_progress: Callback(key, success, error_message)
        retry_count: Number of retries per file on failure

    Returns:
        BatchResult with detailed outcomes

    Example:
        items = [
            BatchUploadItem("file1.txt", b"content1", "text/plain"),
            BatchUploadItem("file2.json", json_bytes, "application/json"),
        ]
        result = await batch_upload(client, items, max_concurrency=10)
        print(f"Success rate: {result.success_rate}%")
    """
    import time
    from io import BytesIO

    start_time = time.perf_counter()
    semaphore = asyncio.Semaphore(max_concurrency)
    results: list[dict[str, Any]] = []

    async def upload_one(item: BatchUploadItem) -> dict[str, Any]:
        async with semaphore:
            last_error: str | None = None

            for attempt in range(retry_count + 1):
                try:
                    # Convert bytes to BinaryIO if needed
                    file_obj = (
                        BytesIO(item.data) if isinstance(item.data, bytes)
                        else item.data
                    )

                    result = await client.upload_file(
                        file_obj=file_obj,
                        key=item.key,
                        content_type=item.content_type,
                        metadata=item.metadata,
                    )

                    if on_progress:
                        on_progress(item.key, True, None)

                    return {
                        "key": item.key,
                        "success": True,
                        "etag": result.get("etag"),
                        "size_bytes": result.get("size_bytes"),
                        "attempts": attempt + 1,
                    }

                except Exception as e:
                    last_error = str(e)
                    if attempt < retry_count:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Backoff
                        continue

            if on_progress:
                on_progress(item.key, False, last_error)

            return {
                "key": item.key,
                "success": False,
                "error": last_error,
                "attempts": retry_count + 1,
            }

    # Execute all uploads
    tasks = [upload_one(item) for item in items]
    results = await asyncio.gather(*tasks)

    duration = time.perf_counter() - start_time
    successful = sum(1 for r in results if r.get("success"))

    return BatchResult(
        total=len(items),
        successful=successful,
        failed=len(items) - successful,
        results=results,
        duration_seconds=duration,
    )


async def batch_download(
    client: Any,  # StorageClient
    keys: list[str],
    max_concurrency: int = 5,
    on_progress: Callable[[str, bool, str | None], None] | None = None,
    retry_count: int = 1,
) -> BatchResult:
    """Download multiple files with enhanced tracking.

    Args:
        client: Storage client instance
        keys: List of S3 object keys
        max_concurrency: Maximum concurrent downloads
        on_progress: Callback(key, success, error_message)
        retry_count: Number of retries per file on failure

    Returns:
        BatchResult with downloaded data in results
    """
    import time

    start_time = time.perf_counter()
    semaphore = asyncio.Semaphore(max_concurrency)
    results: list[dict[str, Any]] = []

    async def download_one(key: str) -> dict[str, Any]:
        async with semaphore:
            last_error: str | None = None

            for attempt in range(retry_count + 1):
                try:
                    data = await client.download_file(key)

                    if on_progress:
                        on_progress(key, True, None)

                    return {
                        "key": key,
                        "success": True,
                        "data": data,
                        "size_bytes": len(data),
                        "attempts": attempt + 1,
                    }

                except Exception as e:
                    last_error = str(e)
                    if attempt < retry_count:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue

            if on_progress:
                on_progress(key, False, last_error)

            return {
                "key": key,
                "success": False,
                "error": last_error,
                "attempts": retry_count + 1,
            }

    tasks = [download_one(key) for key in keys]
    results = await asyncio.gather(*tasks)

    duration = time.perf_counter() - start_time
    successful = sum(1 for r in results if r.get("success"))

    return BatchResult(
        total=len(keys),
        successful=successful,
        failed=len(keys) - successful,
        results=results,
        duration_seconds=duration,
    )


async def batch_delete(
    client: Any,  # StorageClient
    keys: list[str],
    max_concurrency: int = 10,
    dry_run: bool = False,
) -> BatchResult:
    """Delete multiple files with dry-run support.

    Args:
        client: Storage client instance
        keys: List of S3 object keys to delete
        max_concurrency: Maximum concurrent deletes
        dry_run: If True, simulates deletion without actually deleting

    Returns:
        BatchResult with deletion outcomes
    """
    import time

    start_time = time.perf_counter()

    if dry_run:
        # Return simulated results
        results = [{"key": key, "success": True, "dry_run": True} for key in keys]
        return BatchResult(
            total=len(keys),
            successful=len(keys),
            failed=0,
            results=results,
            duration_seconds=time.perf_counter() - start_time,
        )

    semaphore = asyncio.Semaphore(max_concurrency)

    async def delete_one(key: str) -> dict[str, Any]:
        async with semaphore:
            try:
                success = await client.delete_file(key)
                return {"key": key, "success": success}
            except Exception as e:
                return {"key": key, "success": False, "error": str(e)}

    tasks = [delete_one(key) for key in keys]
    results = await asyncio.gather(*tasks)

    duration = time.perf_counter() - start_time
    successful = sum(1 for r in results if r.get("success"))

    return BatchResult(
        total=len(keys),
        successful=successful,
        failed=len(keys) - successful,
        results=results,
        duration_seconds=duration,
    )
