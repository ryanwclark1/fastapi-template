"""Service layer for file upload and management business logic."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, BinaryIO

from sqlalchemy.orm import selectinload

from example_service.core.services.base import BaseService
from example_service.features.files.models import File, FileStatus
from example_service.features.files.repository import (
    FileRepository,
    get_file_repository,
)
from example_service.features.files.schemas import FileCreate
from example_service.features.webhooks.dispatcher import dispatch_event
from example_service.features.webhooks.events import (
    FileEvents,
    build_file_event_payload,
    generate_event_id,
)
from example_service.infra.storage.client import (
    InvalidFileError,
    StorageClient,
    StorageClientError,
    get_storage_client,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FileService(BaseService):
    """Orchestrates file upload and management operations."""

    def __init__(
        self,
        session: AsyncSession,
        storage_client: StorageClient | None = None,
        repository: FileRepository | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._storage = storage_client or get_storage_client()
        self._repository = repository or get_file_repository()

        if self._storage is None:
            raise StorageClientError("Storage client not configured")

    async def _dispatch_thumbnail_task(self, file_id: UUID, content_type: str) -> bool:
        """Queue thumbnail generation for image files if the task is available."""
        if not content_type.startswith("image/"):
            return False

        try:
            from example_service.tasks.files import generate_thumbnails
        except Exception as e:  # pragma: no cover - import errors are non-fatal
            self.logger.warning(
                "Thumbnail task import failed; skipping thumbnail generation",
                extra={"file_id": str(file_id), "error": str(e)},
            )
            return False

        if not generate_thumbnails:
            self.logger.info(
                "Thumbnail task not configured; skipping thumbnail generation",
                extra={"file_id": str(file_id)},
            )
            return False

        try:
            await generate_thumbnails.kiq(file_id=str(file_id))
            self.logger.info(
                "Thumbnail generation queued",
                extra={"file_id": str(file_id)},
            )
            return True
        except Exception as e:
            self.logger.warning(
                "Failed to queue thumbnail generation",
                extra={"file_id": str(file_id), "error": str(e)},
            )
            return False

    def _validate_file(self, content_type: str, size_bytes: int) -> None:
        """Validate file type and size against settings.

        Args:
            content_type: MIME type
            size_bytes: File size in bytes

        Raises:
            InvalidFileError: If validation fails
        """
        settings = self._storage.settings

        # Validate content type
        if not settings.is_content_type_allowed(content_type):
            raise InvalidFileError(
                f"Content type '{content_type}' not allowed. "
                f"Allowed types: {', '.join(settings.allowed_content_types)}"
            )

        # Validate file size
        if size_bytes > settings.max_file_size_bytes:
            max_mb = settings.max_file_size_mb
            actual_mb = size_bytes / (1024 * 1024)
            raise InvalidFileError(
                f"File size {actual_mb:.2f}MB exceeds maximum allowed size of {max_mb}MB"
            )

        if size_bytes <= 0:
            raise InvalidFileError("File size must be greater than 0")

    def _generate_storage_key(
        self,
        filename: str,
        owner_id: str | None = None,
    ) -> str:
        """Generate unique storage key for a file.

        Args:
            filename: Original filename
            owner_id: Optional owner identifier

        Returns:
            Storage key (S3 path)
        """
        settings = self._storage.settings
        file_id = uuid.uuid4()

        # Extract extension
        parts = filename.rsplit(".", 1)
        extension = parts[1] if len(parts) > 1 else ""

        # Build key with prefix, optional owner, file ID, and extension
        key_parts = [settings.upload_prefix.rstrip("/")]

        if owner_id:
            # Include owner in path for easier organization
            key_parts.append(owner_id)

        # Add year/month for time-based partitioning
        now = datetime.now(UTC)
        key_parts.append(f"{now.year}/{now.month:02d}")

        # Add unique file identifier
        filename_part = f"{file_id}"
        if extension:
            filename_part += f".{extension}"
        key_parts.append(filename_part)

        return "/".join(key_parts)

    async def upload_file(
        self,
        file_obj: BinaryIO,
        filename: str,
        content_type: str,
        owner_id: str | None = None,
        is_public: bool = False,
        expires_at: datetime | None = None,
    ) -> File:
        """Upload a file directly (multipart upload).

        Args:
            file_obj: File-like object to upload
            filename: Original filename
            content_type: MIME type
            owner_id: Optional owner identifier
            is_public: Whether file is publicly accessible
            expires_at: Optional expiration timestamp

        Returns:
            Created File record

        Raises:
            InvalidFileError: If file validation fails
            StorageClientError: If upload fails
        """
        # Read file to get size
        file_obj.seek(0)
        file_data = file_obj.read()
        size_bytes = len(file_data)

        # Validate file
        self._validate_file(content_type, size_bytes)

        # Generate storage key
        storage_key = self._generate_storage_key(filename, owner_id)

        # Reset file object
        file_obj.seek(0)

        # Upload to storage
        upload_result = await self._storage.upload_file(
            file_obj=file_obj,
            key=storage_key,
            content_type=content_type,
            metadata={"original_filename": filename},
        )

        # Create database record
        file_create = FileCreate(
            original_filename=filename,
            storage_key=storage_key,
            bucket=upload_result["bucket"],
            content_type=content_type,
            size_bytes=upload_result["size_bytes"],
            checksum_sha256=upload_result["checksum_sha256"],
            etag=upload_result["etag"],
            status=FileStatus.READY,  # Direct upload is immediately ready
            owner_id=owner_id,
            is_public=is_public,
            expires_at=expires_at,
        )

        file = File(**file_create.model_dump())
        created = await self._repository.create(self._session, file)

        self.logger.info(
            "File uploaded",
            extra={
                "file_id": str(created.id),
                "file_name": filename[:50],
                "content_type": content_type,
                "size_bytes": size_bytes,
                "operation": "service.upload_file",
            },
        )

        # Dispatch background task for thumbnails when applicable
        await self._dispatch_thumbnail_task(created.id, content_type)

        # Dispatch webhook event
        await dispatch_event(
            session=self._session,
            event_type=FileEvents.UPLOADED,
            event_id=generate_event_id(FileEvents.UPLOADED),
            payload=build_file_event_payload(created, FileEvents.UPLOADED),
        )

        return created

    async def create_presigned_upload(
        self,
        filename: str,
        content_type: str,
        size_bytes: int,
        owner_id: str | None = None,
        is_public: bool = False,
        expires_at: datetime | None = None,
    ) -> dict:
        """Create presigned upload URL for client-side upload.

        Args:
            filename: Original filename
            content_type: MIME type
            size_bytes: File size in bytes
            owner_id: Optional owner identifier
            is_public: Whether file is publicly accessible
            expires_at: Optional expiration timestamp

        Returns:
            Dictionary with presigned upload data and file ID

        Raises:
            InvalidFileError: If file validation fails
        """
        # Validate file
        self._validate_file(content_type, size_bytes)

        # Generate storage key
        storage_key = self._generate_storage_key(filename, owner_id)

        # Generate presigned upload
        presigned = await self._storage.generate_presigned_upload(
            key=storage_key,
            content_type=content_type,
        )

        # Create pending file record
        file_create = FileCreate(
            original_filename=filename,
            storage_key=storage_key,
            bucket=self._storage.settings.bucket,
            content_type=content_type,
            size_bytes=size_bytes,
            status=FileStatus.PENDING,  # Waiting for upload completion
            owner_id=owner_id,
            is_public=is_public,
            expires_at=expires_at,
        )

        file = File(**file_create.model_dump())
        created = await self._repository.create(self._session, file)

        self.logger.info(
            "Presigned upload created",
            extra={
                "file_id": str(created.id),
                "file_name": filename[:50],
                "content_type": content_type,
                "size_bytes": size_bytes,
                "operation": "service.create_presigned_upload",
            },
        )

        return {
            "upload_url": presigned["url"],
            "upload_fields": presigned["fields"],
            "file_id": created.id,
            "storage_key": storage_key,
            "expires_in": self._storage.settings.presigned_url_expiry_seconds,
        }

    async def complete_upload(
        self,
        file_id: UUID,
        etag: str | None = None,
    ) -> File:
        """Mark presigned upload as complete and verify file exists.

        Args:
            file_id: File UUID
            etag: Optional ETag from S3 upload response

        Returns:
            Updated File record

        Raises:
            ValueError: If file not found or not in PENDING status
            StorageClientError: If file verification fails
        """
        file = await self._repository.get_or_raise(self._session, file_id)

        if file.status != FileStatus.PENDING:
            raise ValueError(f"File {file_id} is not pending upload (status: {file.status.value})")

        # Verify file exists in storage
        file_info = await self._storage.get_file_info(file.storage_key)
        if file_info is None:
            # File not found - mark as failed
            file.status = FileStatus.FAILED
            await self._session.flush()
            raise StorageClientError(f"Uploaded file not found in storage: {file.storage_key}")

        # Update file record with storage info
        if etag:
            file.etag = etag
        elif file_info.get("etag"):
            file.etag = file_info["etag"]

        # Mark as processing for thumbnail generation
        file.status = FileStatus.PROCESSING
        await self._session.flush()

        self.logger.info(
            "Upload completed",
            extra={
                "file_id": str(file_id),
                "storage_key": file.storage_key,
                "operation": "service.complete_upload",
            },
        )

        # Dispatch thumbnail generation if appropriate; keep READY for compatibility
        await self._dispatch_thumbnail_task(file_id, file.content_type)

        file.status = FileStatus.READY
        await self._session.flush()
        await self._session.refresh(file)

        return file

    async def get_file(self, file_id: UUID) -> File | None:
        """Get file by ID.

        Args:
            file_id: File UUID

        Returns:
            File if found, None otherwise
        """
        file = await self._repository.get(self._session, file_id)

        self._lazy.debug(
            lambda: f"service.get_file({file_id}) -> {'found' if file else 'not found'}"
        )
        return file

    async def list_files(
        self,
        owner_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[File]:
        """List files with optional owner filter.

        Args:
            owner_id: Optional owner filter
            limit: Maximum results
            offset: Results to skip

        Returns:
            List of files
        """
        if owner_id:
            files = await self._repository.list_by_owner(
                self._session,
                owner_id,
                limit=limit,
                offset=offset,
            )
        else:
            files = await self._repository.list(
                self._session,
                limit=limit,
                offset=offset,
            )

        result = list(files)
        self._lazy.debug(
            lambda: f"service.list_files(owner_id={owner_id}, limit={limit}, offset={offset}) -> {len(result)} items"
        )
        return result

    async def get_download_url(self, file_id: UUID) -> dict:
        """Generate presigned download URL for a file.

        Args:
            file_id: File UUID

        Returns:
            Dictionary with download URL and metadata

        Raises:
            ValueError: If file not found or not ready
        """
        file = await self._repository.get_or_raise(self._session, file_id)

        if file.status != FileStatus.READY:
            raise ValueError(
                f"File {file_id} is not ready for download (status: {file.status.value})"
            )

        # Generate presigned download URL
        download_url = await self._storage.get_presigned_url(file.storage_key)

        self._lazy.debug(lambda: f"service.get_download_url({file_id}) -> generated presigned URL")

        return {
            "download_url": download_url,
            "expires_in": self._storage.settings.presigned_url_expiry_seconds,
            "filename": file.original_filename,
            "content_type": file.content_type,
            "size_bytes": file.size_bytes,
        }

    async def delete_file(self, file_id: UUID, hard_delete: bool = False) -> bool:
        """Delete a file (soft or hard delete).

        Args:
            file_id: File UUID
            hard_delete: If True, delete from storage; if False, soft delete

        Returns:
            True if deleted successfully

        Raises:
            ValueError: If file not found
        """
        options = [selectinload(File.thumbnails)] if hard_delete else None
        file = await self._repository.get_or_raise(self._session, file_id, options=options)

        if hard_delete:
            # Delete from storage
            try:
                await self._storage.delete_file(file.storage_key)
            except StorageClientError as e:
                self.logger.warning(
                    "Failed to delete file from storage",
                    extra={"file_id": str(file_id), "error": str(e)},
                )

            # Delete thumbnails from storage
            for thumbnail in file.thumbnails:
                with contextlib.suppress(StorageClientError):
                    # Continue even if thumbnail deletion fails
                    await self._storage.delete_file(thumbnail.storage_key)

            # Delete from database
            await self._repository.delete(self._session, file)

            self.logger.info(
                "File hard deleted",
                extra={"file_id": str(file_id), "operation": "service.delete_file"},
            )
        else:
            # Soft delete
            await self._repository.soft_delete(self._session, file_id)

            self.logger.info(
                "File soft deleted",
                extra={"file_id": str(file_id), "operation": "service.delete_file"},
            )

        # Dispatch webhook event
        await dispatch_event(
            session=self._session,
            event_type=FileEvents.DELETED,
            event_id=generate_event_id(FileEvents.DELETED),
            payload=build_file_event_payload(file, FileEvents.DELETED),
        )

        return True

    async def get_processing_status(self, file_id: UUID) -> dict:
        """Get file processing status.

        Args:
            file_id: File UUID

        Returns:
            Dictionary with status information
        """
        file = await self._repository.get_or_raise(self._session, file_id)

        return {
            "file_id": file.id,
            "status": file.status,
            "original_filename": file.original_filename,
            "content_type": file.content_type,
            "size_bytes": file.size_bytes,
            "created_at": file.created_at,
            "updated_at": file.updated_at,
            "thumbnail_count": len(file.thumbnails),
        }

    async def batch_upload_files(
        self,
        files: list[tuple[BinaryIO, str, str]],  # [(file_obj, filename, content_type), ...]
        owner_id: str | None = None,
        is_public: bool = False,
    ) -> dict:
        """Upload multiple files in batch.

        Args:
            files: List of tuples (file_obj, filename, content_type)
            owner_id: Optional owner identifier
            is_public: Whether files are publicly accessible

        Returns:
            Dictionary with batch upload results
        """
        results = []
        successful = 0
        failed = 0

        for file_obj, filename, content_type in files:
            try:
                created_file = await self.upload_file(
                    file_obj=file_obj,
                    filename=filename,
                    content_type=content_type,
                    owner_id=owner_id,
                    is_public=is_public,
                )
                results.append(
                    {
                        "filename": filename,
                        "file_id": created_file.id,
                        "success": True,
                        "error": None,
                    }
                )
                successful += 1
            except (InvalidFileError, StorageClientError) as e:
                results.append(
                    {
                        "filename": filename,
                        "file_id": None,
                        "success": False,
                        "error": str(e),
                    }
                )
                failed += 1

        self.logger.info(
            "Batch upload completed",
            extra={
                "total": len(files),
                "successful": successful,
                "failed": failed,
                "operation": "service.batch_upload_files",
            },
        )

        return {
            "total": len(files),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    async def batch_download_urls(self, file_ids: list[UUID]) -> dict:
        """Generate download URLs for multiple files.

        Args:
            file_ids: List of file UUIDs

        Returns:
            Dictionary with batch download results
        """
        items = []
        successful = 0
        failed = 0

        for file_id in file_ids:
            try:
                file = await self._repository.get(self._session, file_id)
                if file is None:
                    items.append(
                        {
                            "file_id": file_id,
                            "download_url": None,
                            "filename": None,
                            "content_type": None,
                            "size_bytes": None,
                            "success": False,
                            "error": "File not found",
                        }
                    )
                    failed += 1
                    continue

                if file.status != FileStatus.READY:
                    items.append(
                        {
                            "file_id": file_id,
                            "download_url": None,
                            "filename": file.original_filename,
                            "content_type": file.content_type,
                            "size_bytes": file.size_bytes,
                            "success": False,
                            "error": f"File not ready (status: {file.status.value})",
                        }
                    )
                    failed += 1
                    continue

                download_url = await self._storage.get_presigned_url(file.storage_key)
                items.append(
                    {
                        "file_id": file_id,
                        "download_url": download_url,
                        "filename": file.original_filename,
                        "content_type": file.content_type,
                        "size_bytes": file.size_bytes,
                        "success": True,
                        "error": None,
                    }
                )
                successful += 1

            except Exception as e:
                items.append(
                    {
                        "file_id": file_id,
                        "download_url": None,
                        "filename": None,
                        "content_type": None,
                        "size_bytes": None,
                        "success": False,
                        "error": str(e),
                    }
                )
                failed += 1

        self.logger.info(
            "Batch download URLs generated",
            extra={
                "total": len(file_ids),
                "successful": successful,
                "failed": failed,
                "operation": "service.batch_download_urls",
            },
        )

        return {
            "total": len(file_ids),
            "successful": successful,
            "failed": failed,
            "expires_in": self._storage.settings.presigned_url_expiry_seconds,
            "items": items,
        }

    async def batch_delete_files(
        self,
        file_ids: list[UUID],
        dry_run: bool = False,
        hard_delete: bool = False,
    ) -> dict:
        """Delete multiple files in batch.

        Args:
            file_ids: List of file UUIDs
            dry_run: If True, preview deletion without executing
            hard_delete: If True, permanently delete from storage

        Returns:
            Dictionary with batch deletion results
        """
        items = []
        successful = 0
        failed = 0

        for file_id in file_ids:
            try:
                file = await self._repository.get(self._session, file_id)
                if file is None:
                    items.append(
                        {
                            "file_id": file_id,
                            "filename": None,
                            "would_delete": None if dry_run else None,
                            "deleted": None if not dry_run else None,
                            "success": False,
                            "error": "File not found",
                        }
                    )
                    failed += 1
                    continue

                if dry_run:
                    # Dry run - just preview
                    items.append(
                        {
                            "file_id": file_id,
                            "filename": file.original_filename,
                            "would_delete": True,
                            "deleted": None,
                            "success": True,
                            "error": None,
                        }
                    )
                    successful += 1
                else:
                    # Actual deletion
                    await self.delete_file(file_id, hard_delete=hard_delete)
                    items.append(
                        {
                            "file_id": file_id,
                            "filename": file.original_filename,
                            "would_delete": None,
                            "deleted": True,
                            "success": True,
                            "error": None,
                        }
                    )
                    successful += 1

            except Exception as e:
                items.append(
                    {
                        "file_id": file_id,
                        "filename": None,
                        "would_delete": None if dry_run else None,
                        "deleted": None if not dry_run else None,
                        "success": False,
                        "error": str(e),
                    }
                )
                failed += 1

        self.logger.info(
            "Batch delete completed",
            extra={
                "total": len(file_ids),
                "successful": successful,
                "failed": failed,
                "dry_run": dry_run,
                "hard_delete": hard_delete,
                "operation": "service.batch_delete_files",
            },
        )

        return {
            "total": len(file_ids),
            "successful": successful,
            "failed": failed,
            "dry_run": dry_run,
            "hard_delete": hard_delete,
            "items": items,
        }

    async def copy_file(
        self,
        file_id: UUID,
        new_filename: str | None = None,
    ) -> File:
        """Create a copy of a file.

        Args:
            file_id: File UUID to copy
            new_filename: Optional new filename (defaults to "Copy of {original}")

        Returns:
            Created File record

        Raises:
            ValueError: If file not found or not ready
            StorageClientError: If copy operation fails
        """
        source_file = await self._repository.get_or_raise(self._session, file_id)

        if source_file.status != FileStatus.READY:
            raise ValueError(
                f"Cannot copy file {file_id} - not ready (status: {source_file.status.value})"
            )

        # Generate new filename
        if new_filename is None:
            new_filename = f"Copy of {source_file.original_filename}"

        # Generate new storage key
        new_storage_key = self._generate_storage_key(new_filename, source_file.owner_id)

        # Copy file in storage
        await self._storage.copy_file(
            source_key=source_file.storage_key,
            dest_key=new_storage_key,
        )

        # Get file info to get the new etag
        file_info = await self._storage.get_file_info(new_storage_key)

        # Create new database record
        file_create = FileCreate(
            original_filename=new_filename,
            storage_key=new_storage_key,
            bucket=source_file.bucket,
            content_type=source_file.content_type,
            size_bytes=source_file.size_bytes,
            checksum_sha256=source_file.checksum_sha256,
            etag=file_info.get("etag") if file_info else None,
            status=FileStatus.READY,
            owner_id=source_file.owner_id,
            is_public=source_file.is_public,
            expires_at=source_file.expires_at,
        )

        file = File(**file_create.model_dump())
        new_file = await self._repository.create(self._session, file)

        self.logger.info(
            "File copied",
            extra={
                "source_file_id": str(file_id),
                "new_file_id": str(new_file.id),
                "new_filename": new_filename,
                "operation": "service.copy_file",
            },
        )

        # Dispatch webhook event
        await dispatch_event(
            session=self._session,
            event_type=FileEvents.COPIED,
            event_id=generate_event_id(FileEvents.COPIED),
            payload=build_file_event_payload(
                new_file,
                FileEvents.COPIED,
                extra={"source_file_id": str(source_file.id)},
            ),
        )

        return new_file

    async def move_file(
        self,
        file_id: UUID,
        new_filename: str,
    ) -> File:
        """Move/rename a file.

        Args:
            file_id: File UUID to move/rename
            new_filename: New filename

        Returns:
            Updated File record

        Raises:
            ValueError: If file not found
        """
        file = await self._repository.get_or_raise(self._session, file_id)

        # Store old filename for webhook event
        old_filename = file.original_filename

        # Update filename in database
        file.original_filename = new_filename
        await self._session.flush()
        await self._session.refresh(file)

        self.logger.info(
            "File renamed",
            extra={
                "file_id": str(file_id),
                "new_filename": new_filename,
                "operation": "service.move_file",
            },
        )

        # Dispatch webhook event
        await dispatch_event(
            session=self._session,
            event_type=FileEvents.MOVED,
            event_id=generate_event_id(FileEvents.MOVED),
            payload=build_file_event_payload(
                file,
                FileEvents.MOVED,
                extra={"old_filename": old_filename},
            ),
        )

        return file


__all__ = ["FileService"]
