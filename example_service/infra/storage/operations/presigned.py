"""Presigned URL operations for storage service.

Provides presigned URL generation with:
- Download URLs with custom expiry
- Upload URLs for browser-based uploads (POST)
- URL validation and security options
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PresignedDownloadUrl:
    """Presigned download URL with metadata."""

    url: str
    key: str
    expires_at: datetime
    expires_in_seconds: int

    def is_expired(self) -> bool:
        """Check if the URL has expired."""
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "url": self.url,
            "key": self.key,
            "expires_at": self.expires_at.isoformat(),
            "expires_in_seconds": self.expires_in_seconds,
        }


@dataclass
class PresignedUploadUrl:
    """Presigned upload URL for browser POST uploads."""

    url: str
    fields: dict[str, str]
    key: str
    expires_at: datetime
    expires_in_seconds: int
    content_type: str
    max_size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "url": self.url,
            "fields": self.fields,
            "key": self.key,
            "expires_at": self.expires_at.isoformat(),
            "expires_in_seconds": self.expires_in_seconds,
            "content_type": self.content_type,
        }
        if self.max_size_bytes:
            result["max_size_bytes"] = self.max_size_bytes
        return result


async def generate_download_url(
    client: Any,  # StorageClient
    key: str,
    expires_in: int | None = None,
    bucket: str | None = None,
    response_content_disposition: str | None = None,
    response_content_type: str | None = None,
) -> PresignedDownloadUrl:
    """Generate a presigned download URL with metadata.

    Args:
        client: Storage client instance
        key: S3 object key
        expires_in: Expiry in seconds (uses default if not provided)
        bucket: Optional bucket override
        response_content_disposition: Force Content-Disposition header
        response_content_type: Force Content-Type header

    Returns:
        PresignedDownloadUrl with URL and expiry info

    Example:
        url = await generate_download_url(
            client,
            "reports/2024/q1.pdf",
            expires_in=3600,
            response_content_disposition='attachment; filename="Q1_Report.pdf"',
        )
    """
    expires_in = expires_in or client.settings.presigned_url_expiry_seconds

    # Build extra params for response headers
    params: dict[str, Any] = {}
    if response_content_disposition:
        params["ResponseContentDisposition"] = response_content_disposition
    if response_content_type:
        params["ResponseContentType"] = response_content_type

    url = await client.get_presigned_url(key, expires_in, bucket)

    return PresignedDownloadUrl(
        url=url,
        key=key,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        expires_in_seconds=expires_in,
    )


async def generate_upload_url(
    client: Any,  # StorageClient
    key: str,
    content_type: str,
    expires_in: int | None = None,
    bucket: str | None = None,
    max_size_bytes: int | None = None,
    metadata: dict[str, str] | None = None,  # noqa: ARG001
) -> PresignedUploadUrl:
    """Generate a presigned upload URL for browser uploads.

    Creates a presigned POST URL that allows browsers to upload
    directly to S3 without going through the server.

    Args:
        client: Storage client instance
        key: S3 object key for the upload
        content_type: Expected content type
        expires_in: Expiry in seconds
        bucket: Optional bucket override
        max_size_bytes: Maximum allowed file size
        metadata: Custom metadata to include

    Returns:
        PresignedUploadUrl with URL, fields, and constraints

    Example:
        upload = await generate_upload_url(
            client,
            "uploads/user123/photo.jpg",
            "image/jpeg",
            max_size_bytes=10 * 1024 * 1024,  # 10MB
        )
        # Return to frontend for direct upload
    """
    expires_in = expires_in or client.settings.presigned_url_expiry_seconds

    result = await client.generate_presigned_upload(key, content_type, expires_in, bucket)

    return PresignedUploadUrl(
        url=result["url"],
        fields=result["fields"],
        key=key,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        expires_in_seconds=expires_in,
        content_type=content_type,
        max_size_bytes=max_size_bytes,
    )


async def generate_bulk_download_urls(
    client: Any,  # StorageClient
    keys: list[str],
    expires_in: int | None = None,
    bucket: str | None = None,
) -> list[PresignedDownloadUrl]:
    """Generate presigned download URLs for multiple files.

    Args:
        client: Storage client instance
        keys: List of S3 object keys
        expires_in: Expiry in seconds (same for all URLs)
        bucket: Optional bucket override

    Returns:
        List of PresignedDownloadUrl objects
    """
    import asyncio

    async def generate_one(key: str) -> PresignedDownloadUrl:
        return await generate_download_url(client, key, expires_in, bucket)

    tasks = [generate_one(key) for key in keys]
    return await asyncio.gather(*tasks)
