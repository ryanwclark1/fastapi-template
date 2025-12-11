"""File processing task definitions.

This module provides:
- Uploaded file validation and processing
- Image thumbnail generation using Pillow
- Automated cleanup of expired files
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from example_service.core.settings import get_storage_settings
from example_service.infra.database.session import get_async_session
from example_service.infra.storage import get_storage_service
from example_service.infra.storage.client import (
    FileNotFoundError as StorageFileNotFoundError,
)
from example_service.infra.storage.client import (
    InvalidFileError,
    StorageClientError,
)
from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)


class FileProcessingError(Exception):
    """File processing operation error."""


async def get_file_from_storage(file_id: str) -> dict[str, Any]:
    """Retrieve file metadata and content from storage.

    This is a placeholder that should be replaced with actual storage backend.

    Args:
        file_id: Unique file identifier.

    Returns:
        Dictionary containing file metadata and content.

    Raises:
        StorageFileNotFoundError: If file does not exist.
    """
    from example_service.features.files.models import File

    async with get_async_session() as session:
        result = await session.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()

        if not file:
            msg = f"File {file_id} not found"
            raise StorageFileNotFoundError(msg)

        return {
            "id": str(file.id),
            "filename": file.original_filename,
            "content_type": file.content_type,
            "s3_key": file.storage_key,
            "status": file.status if hasattr(file, "status") else str(file.status),
            "size_bytes": file.size_bytes,
        }


async def update_file_status(
    file_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update file status in database.

    Args:
        file_id: Unique file identifier.
        status: New status (ready, failed, processing).
        error_message: Optional error message if status is failed.
    """
    from example_service.features.files.models import File, FileStatus

    async with get_async_session() as session:
        result = await session.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            logger.warning(
                "File not found while updating status", extra={"file_id": file_id},
            )
            return

        # Update status and timestamps
        try:
            file.status = FileStatus(status)
        except Exception:
            file.status = status
        file.updated_at = datetime.now(UTC)

        if hasattr(file, "error_message"):
            file.error_message = error_message

        await session.commit()

    logger.info(
        "File status updated",
        extra={
            "file_id": file_id,
            "status": status,
            "error_message": error_message,
        },
    )


def _validate_file_metadata(file_data: dict[str, Any]) -> None:
    """Validate file metadata against storage settings."""
    settings = get_storage_settings()

    content_type = file_data.get("content_type") or ""
    if (
        settings.allowed_content_types
        and content_type not in settings.allowed_content_types
    ):
        msg = f"Content type '{content_type}' not allowed"
        raise InvalidFileError(msg)

    size_bytes = file_data.get("size_bytes")
    if size_bytes is not None and size_bytes > settings.max_file_size_bytes:
        msg = f"File size {size_bytes} exceeds max {settings.max_file_size_bytes} bytes"
        raise InvalidFileError(
            msg,
        )
    if size_bytes is not None and size_bytes <= 0:
        msg = "File size must be greater than 0"
        raise InvalidFileError(msg)


async def download_from_s3(s3_key: str) -> bytes:
    """Download file content from S3.

    Args:
        s3_key: S3 object key.

    Returns:
        File content as bytes.

    Raises:
        FileProcessingError: If download fails.
    """
    storage = get_storage_service()
    if not storage.is_ready:
        msg = "Storage not available for downloads"
        raise FileProcessingError(msg)

    try:
        return await storage.download_file(s3_key)
    except StorageClientError as e:
        msg = f"Failed to download {s3_key}: {e}"
        raise FileProcessingError(msg) from e


async def upload_to_s3(s3_key: str, content: bytes, content_type: str) -> str:
    """Upload file content to S3.

    Args:
        s3_key: S3 object key.
        content: File content as bytes.
        content_type: MIME type of content (currently unused in placeholder).

    Returns:
        S3 URI of uploaded file.

    Raises:
        FileProcessingError: If upload fails.
    """
    storage = get_storage_service()
    if not storage.is_ready:
        msg = "Storage not available for uploads"
        raise FileProcessingError(msg)

    try:
        result = await storage.upload_file(
            file_obj=io.BytesIO(content),
            key=s3_key,
            content_type=content_type,
            metadata={},
        )
        bucket = result.get("bucket", storage.settings.bucket)
        return f"s3://{bucket}/{s3_key}"
    except StorageClientError as e:
        msg = f"Failed to upload {s3_key}: {e}"
        raise FileProcessingError(msg) from e


async def create_thumbnail_record(
    file_id: str,
    size: int,
    s3_key: str,
) -> None:
    """Create FileThumbnail record in database.

    Args:
        file_id: Parent file identifier.
        size: Thumbnail size in pixels.
        s3_key: S3 key where thumbnail is stored.
    """
    from example_service.features.files.models import FileThumbnail

    async with get_async_session() as session:
        thumbnail = FileThumbnail(
            file_id=file_id,
            storage_key=s3_key,
            width=size,
            height=size,
            size_bytes=0,  # Set actual size after upload if available
        )
        session.add(thumbnail)
        await session.commit()

    logger.info(
        "Thumbnail record created",
        extra={
            "file_id": file_id,
            "size": size,
            "s3_key": s3_key,
        },
    )


async def find_expired_files(expiry_days: int = 30) -> list[dict[str, Any]]:
    """Find files that have expired and should be deleted.

    Args:
        expiry_days: Number of days after which files are considered expired.

    Returns:
        List of expired file dictionaries.
    """
    from example_service.features.files.models import File, FileStatus

    cutoff = datetime.now(UTC) - timedelta(days=expiry_days)

    async with get_async_session() as session:
        result = await session.execute(
            select(File)
            .options(selectinload(File.thumbnails))
            .where(
                (
                    (
                        File.expires_at.is_not(None)
                        & (File.expires_at < datetime.now(UTC))
                    )
                    | (File.expires_at.is_(None) & (File.created_at < cutoff))
                ),
                File.status == FileStatus.READY,
            ),
        )
        files = result.scalars().all()

    return [
        {
            "id": str(file.id),
            "s3_key": file.storage_key,
            "created_at": file.created_at,
            "thumbnails": [t.storage_key for t in file.thumbnails],
        }
        for file in files
    ]


async def delete_file_from_storage(s3_key: str) -> None:
    """Delete file from S3 storage.

    Args:
        s3_key: S3 object key to delete.
    """
    storage = get_storage_service()
    if not storage.is_ready:
        logger.warning(
            "Storage not available; skipping delete", extra={"s3_key": s3_key},
        )
        return

    try:
        await storage.delete_file(s3_key)
        logger.info("File deleted from storage", extra={"s3_key": s3_key})
    except StorageClientError as e:
        logger.warning(
            "Failed to delete file from storage",
            extra={"s3_key": s3_key, "error": str(e)},
        )


async def delete_thumbnails(thumbnail_keys: list[str]) -> None:
    """Delete thumbnail objects from storage."""
    if not thumbnail_keys:
        return

    storage = get_storage_service()
    if not storage.is_ready:
        logger.warning(
            "Storage not available; skipping thumbnail deletes",
            extra={"count": len(thumbnail_keys)},
        )
        return

    for key in thumbnail_keys:
        try:
            await storage.delete_file(key)
            logger.debug("Deleted thumbnail", extra={"s3_key": key})
        except StorageClientError as e:
            logger.warning(
                "Failed to delete thumbnail", extra={"s3_key": key, "error": str(e)},
            )


async def delete_file_record(file_id: str) -> None:
    """Delete file record from database.

    Args:
        file_id: File identifier to delete.
    """
    from example_service.features.files.models import File

    async with get_async_session() as session:
        await session.execute(delete(File).where(File.id == file_id))
        await session.commit()

    logger.info(
        "File record deleted",
        extra={"file_id": file_id},
    )


if broker is not None:

    @broker.task(retry_on_error=True, max_retries=3)
    async def process_uploaded_file(file_id: str) -> dict[str, Any]:
        """Process uploaded file and update status.

        This task validates the uploaded file, performs any necessary processing,
        and updates the file status to ready or failed.

        Args:
            file_id: Unique identifier of the uploaded file.

        Returns:
            Processing result dictionary.

        Raises:
            FileProcessingError: If file processing fails.

        Example:
                    # Schedule file processing
            from example_service.workers.files import process_uploaded_file
            task = await process_uploaded_file.kiq(file_id="abc123")
            result = await task.wait_result()
        """
        logger.info(
            "Processing uploaded file",
            extra={"file_id": file_id},
        )

        try:
            # Step 1: Retrieve file metadata
            file_data = await get_file_from_storage(file_id)

            # Step 2: Update status to processing
            await update_file_status(file_id, status="processing")

            # Step 3: Validate file (size, type, content)
            _validate_file_metadata(file_data)

            logger.info(
                "File validation completed",
                extra={
                    "file_id": file_id,
                    "filename": file_data["filename"],
                    "content_type": file_data["content_type"],
                },
            )

            # Step 4: Additional processing based on file type
            is_image = file_data["content_type"].startswith("image/")

            if is_image:
                # Queue thumbnail generation for images
                logger.info(
                    "Queuing thumbnail generation",
                    extra={"file_id": file_id},
                )
                await generate_thumbnails.kiq(file_id=file_id)

            # Step 5: Update status to ready
            await update_file_status(file_id, status="ready")

            result = {
                "status": "success",
                "file_id": file_id,
                "filename": file_data["filename"],
                "content_type": file_data["content_type"],
                "is_image": is_image,
                "thumbnails_queued": is_image,
            }

            logger.info(
                "File processing completed successfully",
                extra=result,
            )

            return result

        except StorageFileNotFoundError as e:
            logger.exception(
                "File not found",
                extra={"file_id": file_id, "error": str(e)},
            )
            await update_file_status(
                file_id,
                status="failed",
                error_message="File not found",
            )
            msg = f"File not found: {file_id}"
            raise FileProcessingError(msg) from e

        except Exception as e:
            logger.exception(
                "File processing failed",
                extra={"file_id": file_id, "error": str(e)},
            )
            await update_file_status(
                file_id,
                status="failed",
                error_message=str(e),
            )
            msg = f"Failed to process file {file_id}: {e}"
            raise FileProcessingError(msg) from e

    @broker.task(retry_on_error=True, max_retries=2)
    async def generate_thumbnails(file_id: str) -> dict[str, Any]:
        """Generate image thumbnails at multiple sizes.

        Creates thumbnails at 128px, 256px, and 512px sizes using Pillow.
        Thumbnails are saved to S3 with the key pattern: thumbnails/{file_id}/{size}.jpg

        Args:
            file_id: Unique identifier of the image file.

        Returns:
            Thumbnail generation result dictionary.

        Raises:
            FileProcessingError: If thumbnail generation fails.

        Example:
                    # Generate thumbnails for an image
            from example_service.workers.files import generate_thumbnails
            task = await generate_thumbnails.kiq(file_id="abc123")
            result = await task.wait_result()
        """
        logger.info(
            "Generating thumbnails",
            extra={"file_id": file_id},
        )

        try:
            # Import Pillow
            from PIL import Image

            # Step 1: Retrieve file metadata
            file_data = await get_file_from_storage(file_id)

            # Step 2: Validate it's an image
            if not file_data["content_type"].startswith("image/"):
                msg = f"File is not an image: {file_data['content_type']}"
                raise FileProcessingError(
                    msg,
                )

            # Step 3: Download image from S3
            image_bytes = await download_from_s3(file_data["s3_key"])

            if not image_bytes:
                logger.warning(
                    "Placeholder S3 download returned empty bytes - "
                    "skipping actual thumbnail generation",
                    extra={"file_id": file_id},
                )
                return {
                    "status": "skipped",
                    "file_id": file_id,
                    "reason": "placeholder_implementation",
                }

            # Step 4: Open image with Pillow
            image = Image.open(io.BytesIO(image_bytes))

            # Convert to RGB if necessary (e.g., RGBA, P mode)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            logger.info(
                "Image loaded",
                extra={
                    "file_id": file_id,
                    "size": image.size,
                    "mode": image.mode,
                    "format": image.format,
                },
            )

            # Step 5: Generate thumbnails at different sizes
            thumbnail_sizes = [128, 256, 512]
            generated_thumbnails = []

            for size in thumbnail_sizes:
                # Create thumbnail
                thumbnail = image.copy()
                thumbnail.thumbnail((size, size), Image.Resampling.LANCZOS)

                # Convert to bytes
                buffer = io.BytesIO()
                thumbnail.save(buffer, format="JPEG", quality=85, optimize=True)
                thumbnail_bytes = buffer.getvalue()

                # Upload to S3
                s3_key = f"thumbnails/{file_id}/{size}.jpg"
                s3_uri = await upload_to_s3(
                    s3_key=s3_key,
                    content=thumbnail_bytes,
                    content_type="image/jpeg",
                )

                # Create database record
                await create_thumbnail_record(
                    file_id=file_id,
                    size=size,
                    s3_key=s3_key,
                )

                generated_thumbnails.append({
                    "size": size,
                    "s3_key": s3_key,
                    "s3_uri": s3_uri,
                    "dimensions": thumbnail.size,
                    "size_bytes": len(thumbnail_bytes),
                })

                logger.info(
                    "Thumbnail generated",
                    extra={
                        "file_id": file_id,
                        "size": size,
                        "s3_key": s3_key,
                    },
                )

            result = {
                "status": "success",
                "file_id": file_id,
                "thumbnails": generated_thumbnails,
                "total_thumbnails": len(generated_thumbnails),
            }

            logger.info(
                "Thumbnail generation completed successfully",
                extra=result,
            )

            return result

        except ImportError as e:
            logger.exception(
                "Pillow not installed",
                extra={"file_id": file_id, "error": str(e)},
            )
            msg = "Pillow library required for thumbnail generation"
            raise FileProcessingError(msg) from e

        except Exception as e:
            logger.exception(
                "Thumbnail generation failed",
                extra={"file_id": file_id, "error": str(e)},
            )
            msg = f"Failed to generate thumbnails for file {file_id}: {e}"
            raise FileProcessingError(
                msg,
            ) from e

    @broker.task()
    async def cleanup_expired_files() -> dict[str, Any]:
        """Scheduled task to delete expired files.

        Finds files older than the expiry threshold and removes them from
        both storage (S3) and database.

        Scheduled: Daily at 2 AM (can be configured via scheduler).

        Returns:
            Cleanup result dictionary with counts of deleted files.

        Example:
                    # Manually trigger cleanup
            from example_service.workers.files import cleanup_expired_files
            task = await cleanup_expired_files.kiq()
            result = await task.wait_result()
        """
        logger.info("Starting expired file cleanup")

        try:
            # Step 1: Find expired files
            # Default: files older than 30 days
            expiry_days = 30
            expired_files = await find_expired_files(expiry_days=expiry_days)

            if not expired_files:
                logger.info("No expired files found")
                return {
                    "status": "success",
                    "deleted_count": 0,
                    "expiry_days": expiry_days,
                }

            logger.info(
                "Found expired files",
                extra={
                    "count": len(expired_files),
                    "expiry_days": expiry_days,
                },
            )

            # Step 2: Delete files from storage and database
            deleted_count = 0
            failed_count = 0

            for file in expired_files:
                try:
                    # Delete from S3
                    await delete_file_from_storage(file["s3_key"])

                    # Delete thumbnails if they exist
                    await delete_thumbnails(file.get("thumbnails", []))

                    # Delete database record
                    await delete_file_record(file["id"])

                    deleted_count += 1

                    logger.debug(
                        "Expired file deleted",
                        extra={
                            "file_id": file["id"],
                            "s3_key": file["s3_key"],
                            "created_at": file["created_at"],
                        },
                    )

                except Exception as e:
                    failed_count += 1
                    logger.warning(
                        "Failed to delete expired file",
                        extra={
                            "file_id": file["id"],
                            "error": str(e),
                        },
                    )

            result = {
                "status": "success",
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "total_found": len(expired_files),
                "expiry_days": expiry_days,
            }

            logger.info(
                "Expired file cleanup completed",
                extra=result,
            )

            return result

        except Exception as e:
            logger.exception(
                "Expired file cleanup failed",
                extra={"error": str(e)},
            )
            raise
