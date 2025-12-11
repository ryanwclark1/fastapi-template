"""Background job processing for data transfer operations.

Provides async background job execution with progress tracking
for long-running export and import operations.

This module integrates with the JobManager for persistent job storage
while maintaining backward compatibility with the legacy JobTracker interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from example_service.infra.tasks.jobs.enums import JobStatus as JobManagerStatus
from example_service.infra.tasks.jobs.manager import JobManager, JobNotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.tasks.jobs.models import Job

    from .schemas import ExportRequest, ImportFormat

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """Status of a background job.

    Note: This enum is kept for backward compatibility.
    Internally mapped to JobManager's JobStatus enum.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    """Type of background job."""

    EXPORT = "export"
    IMPORT = "import"


@dataclass
class JobProgress:
    """Progress information for a background job.

    Legacy model kept for backward compatibility.
    Internally maps to JobManager's Job + JobProgress models.
    """

    job_id: str
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    entity_type: str = ""
    total_records: int = 0
    processed_records: int = 0
    successful_records: int = 0
    failed_records: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result_data: dict[str, Any] = field(default_factory=dict)

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_records == 0:
            return 0.0
        return min(100.0, (self.processed_records / self.total_records) * 100)

    @property
    def elapsed_seconds(self) -> float | None:
        """Calculate elapsed time in seconds."""
        if self.started_at is None:
            return None
        end_time = self.completed_at or datetime.now(UTC)
        return (end_time - self.started_at).total_seconds()

    @property
    def estimated_remaining_seconds(self) -> float | None:
        """Estimate remaining time based on current progress."""
        if self.elapsed_seconds is None or self.processed_records == 0:
            return None
        rate = self.processed_records / self.elapsed_seconds
        remaining = self.total_records - self.processed_records
        return remaining / rate if rate > 0 else None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "entity_type": self.entity_type,
            "total_records": self.total_records,
            "processed_records": self.processed_records,
            "successful_records": self.successful_records,
            "failed_records": self.failed_records,
            "progress_percent": round(self.progress_percent, 2),
            "elapsed_seconds": self.elapsed_seconds,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "result_data": self.result_data,
        }


class JobTracker:
    """Tracks background job progress with persistent storage.

    Replaces the in-memory job tracker with JobManager for database persistence.
    Maintains backward compatibility with the legacy interface while providing
    durability across service restarts.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize job tracker with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session
        self.job_manager = JobManager(session)

    def _convert_status_to_manager(self, status: JobStatus) -> JobManagerStatus:
        """Convert legacy JobStatus to JobManager status.

        Args:
            status: Legacy job status.

        Returns:
            JobManager status enum value.
        """
        mapping = {
            JobStatus.PENDING: JobManagerStatus.PENDING,
            JobStatus.RUNNING: JobManagerStatus.RUNNING,
            JobStatus.COMPLETED: JobManagerStatus.COMPLETED,
            JobStatus.FAILED: JobManagerStatus.FAILED,
            JobStatus.CANCELLED: JobManagerStatus.CANCELLED,
        }
        return mapping.get(status, JobManagerStatus.PENDING)

    def _convert_status_from_manager(self, status: JobManagerStatus | str) -> JobStatus:
        """Convert JobManager status to legacy JobStatus.

        Args:
            status: JobManager status (enum or string).

        Returns:
            Legacy job status.
        """
        # Handle both enum and string values
        status_str = status.value if isinstance(status, JobManagerStatus) else status

        mapping = {
            "pending": JobStatus.PENDING,
            "queued": JobStatus.PENDING,  # Map QUEUED to PENDING for simplicity
            "running": JobStatus.RUNNING,
            "completed": JobStatus.COMPLETED,
            "failed": JobStatus.FAILED,
            "cancelled": JobStatus.CANCELLED,
            "retrying": JobStatus.RUNNING,  # Map RETRYING to RUNNING
            "paused": JobStatus.PENDING,  # Map PAUSED to PENDING
        }
        return mapping.get(status_str, JobStatus.PENDING)

    def _job_to_progress(self, job: Job) -> JobProgress:
        """Convert JobManager Job to legacy JobProgress.

        Args:
            job: JobManager job instance.

        Returns:
            Legacy JobProgress instance.
        """
        # Extract progress information
        progress_record = job.progress[0] if job.progress else None

        # Extract metadata from labels
        labels_dict = {label.key: label.value for label in job.labels} if job.labels else {}
        job_type_str = labels_dict.get("operation", "export")
        entity_type = labels_dict.get("entity", "unknown")

        # Extract counts from result_data or progress
        total_records = 0
        processed_records = 0
        successful_records = 0
        failed_records = 0

        if progress_record:
            total_records = progress_record.total_items or 0
            processed_records = progress_record.current_item or 0

        if job.result_data:
            # Override with final counts if available
            total_records = job.result_data.get("total_records", total_records)
            successful_records = job.result_data.get("record_count", 0)
            failed_records = job.result_data.get("failed_records", 0)

        return JobProgress(
            job_id=str(job.id),
            job_type=JobType(job_type_str),
            status=self._convert_status_from_manager(job.status),
            entity_type=entity_type,
            total_records=total_records,
            processed_records=processed_records,
            successful_records=successful_records,
            failed_records=failed_records,
            started_at=job.started_at or job.created_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            result_data=job.result_data or {},
        )

    async def create_job(
        self,
        job_type: JobType,
        entity_type: str,
        total_records: int = 0,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> JobProgress:
        """Create a new job and return its progress tracker.

        Args:
            job_type: Type of job (export or import).
            entity_type: Entity type being processed.
            total_records: Total number of records (if known).
            tenant_id: Optional tenant ID for multi-tenancy.
            user_id: Optional user ID who initiated the job.

        Returns:
            JobProgress instance for tracking.
        """
        # Create via JobManager
        job = await self.job_manager.submit(
            tenant_id=tenant_id or "default",
            task_name=f"datatransfer.{job_type.value}",
            args={"entity_type": entity_type, "total_records": total_records},
            labels={
                "feature": "datatransfer",
                "operation": job_type.value,
                "entity": entity_type,
            },
            actor_id=user_id,
        )

        # Update progress with total if known
        if total_records > 0:
            await self.job_manager.update_progress(
                job.id,
                percentage=0,
                total_items=total_records,
                current_item=0,
                message=f"Initializing {job_type.value}",
            )

        await self.session.commit()

        logger.info(
            "Created background job",
            extra={
                "job_id": str(job.id),
                "job_type": job_type,
                "entity_type": entity_type,
            },
        )

        return self._job_to_progress(job)

    async def start_job(self, job_id: str) -> None:
        """Mark a job as started.

        Args:
            job_id: ID of the job to start.
        """
        try:
            await self.job_manager.mark_running(UUID(job_id))
            await self.session.commit()
        except JobNotFoundError:
            logger.warning("Attempted to start non-existent job", extra={"job_id": job_id})

    async def update_progress(
        self,
        job_id: str,
        processed: int,
        successful: int = 0,
        failed: int = 0,
        total: int | None = None,
    ) -> None:
        """Update job progress.

        Args:
            job_id: ID of the job.
            processed: Number of records processed so far.
            successful: Number of successful records.
            failed: Number of failed records.
            total: Update total if now known.
        """
        total_items = total if total is not None else processed
        percentage = int(processed / total_items * 100) if total_items > 0 else 0

        await self.job_manager.update_progress(
            UUID(job_id),
            percentage=percentage,
            current_item=processed,
            total_items=total_items,
            message=f"Processed {processed}/{total_items} ({successful} successful, {failed} failed)",
        )

        # Store detailed counts in job's result_data for later retrieval
        job = await self.job_manager.get(UUID(job_id))
        if job:
            if job.result_data is None:
                job.result_data = {}
            job.result_data.update({
                "processed_records": processed,
                "successful_records": successful,
                "failed_records": failed,
                "total_records": total_items,
            })

        await self.session.commit()

    async def complete_job(
        self,
        job_id: str,
        result_data: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as completed.

        Args:
            job_id: ID of the job.
            result_data: Optional result data to store.
        """
        await self.job_manager.mark_completed(
            UUID(job_id),
            result_data=result_data or {},
        )
        await self.session.commit()

        logger.info(
            "Job completed",
            extra={"job_id": job_id},
        )

    async def fail_job(self, job_id: str, error_message: str) -> None:
        """Mark a job as failed.

        Args:
            job_id: ID of the job.
            error_message: Error message describing the failure.
        """
        await self.job_manager.mark_failed(
            UUID(job_id),
            error_message=error_message,
            should_retry=False,  # Data transfer jobs typically don't auto-retry
        )
        await self.session.commit()

        logger.error(
            "Job failed",
            extra={"job_id": job_id, "error": error_message},
        )

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job if it's still pending or running.

        Args:
            job_id: ID of the job to cancel.

        Returns:
            True if cancelled, False if not found or already completed.
        """
        try:
            result = await self.job_manager.cancel(
                UUID(job_id),
                reason="User requested cancellation",
            )
            await self.session.commit()
            return result
        except JobNotFoundError:
            logger.warning("Attempted to cancel non-existent job", extra={"job_id": job_id})
            return False

    async def get_job(self, job_id: str) -> JobProgress | None:
        """Get job progress by ID.

        Args:
            job_id: ID of the job.

        Returns:
            JobProgress if found, None otherwise.
        """
        try:
            job = await self.job_manager.get(UUID(job_id), include_relations=True)
            if job:
                return self._job_to_progress(job)
            return None
        except (JobNotFoundError, ValueError):
            return None

    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[JobProgress]:
        """List jobs with optional filtering.

        Args:
            job_type: Filter by job type.
            status: Filter by status.
            limit: Maximum number of jobs to return.
            tenant_id: Filter by tenant ID.

        Returns:
            List of matching jobs.
        """
        # Build label filters
        labels = {"feature": "datatransfer"}
        if job_type:
            labels["operation"] = job_type.value

        # Convert status if provided
        manager_status = None
        if status:
            manager_status = self._convert_status_to_manager(status)

        # Query jobs
        jobs = await self.job_manager.get_by_labels(
            tenant_id=tenant_id or "default",
            labels=labels,
            status=manager_status,
            limit=limit,
        )

        return [self._job_to_progress(job) for job in jobs]

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Remove completed jobs older than max_age_hours.

        Note: This is handled by JobManager's TTL cleanup.
        Kept for backward compatibility but delegates to JobManager.

        Args:
            max_age_hours: Maximum age in hours for completed jobs.

        Returns:
            Number of jobs removed (always 0 - handled by background cleanup).
        """
        # JobManager handles cleanup via background tasks
        # This method is kept for backward compatibility
        logger.info(
            "Cleanup requested - handled by JobManager background tasks",
            extra={"max_age_hours": max_age_hours},
        )
        return 0


def get_job_tracker(session: AsyncSession) -> JobTracker:
    """Get a job tracker instance.

    Args:
        session: Database session for job persistence.

    Returns:
        JobTracker instance backed by JobManager.

    Note:
        This no longer uses a singleton pattern. Each call creates
        a new tracker instance with the provided session.
    """
    return JobTracker(session)


async def run_export_job(
    session: AsyncSession,
    request: ExportRequest,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> JobProgress:
    """Run an export as a background job with progress tracking.

    Args:
        session: Database session.
        request: Export request.
        tenant_id: Optional tenant ID.
        user_id: Optional user ID who initiated the export.

    Returns:
        JobProgress with results.
    """
    from .service import DataTransferService

    tracker = get_job_tracker(session)
    job = await tracker.create_job(
        job_type=JobType.EXPORT,
        entity_type=request.entity_type,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    try:
        await tracker.start_job(job.job_id)

        service = DataTransferService(session)
        result = await service.export(request, tenant_id=tenant_id)

        await tracker.update_progress(
            job.job_id,
            processed=result.record_count,
            successful=result.record_count,
            total=result.record_count,
        )

        await tracker.complete_job(
            job.job_id,
            result_data={
                "export_id": result.export_id,
                "file_path": result.file_path,
                "file_name": result.file_name,
                "record_count": result.record_count,
                "size_bytes": result.size_bytes,
            },
        )

    except Exception as e:
        await tracker.fail_job(job.job_id, str(e))
        logger.exception("Export job failed", extra={"job_id": job.job_id})

    return await tracker.get_job(job.job_id) or job


async def run_import_job(
    session: AsyncSession,
    data: bytes,
    entity_type: str,
    format: ImportFormat,
    validate_only: bool = False,
    skip_errors: bool = False,
    update_existing: bool = False,
    batch_size: int = 100,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> JobProgress:
    """Run an import as a background job with progress tracking.

    Args:
        session: Database session.
        data: File data to import.
        entity_type: Entity type to import.
        format: Import file format.
        validate_only: Only validate, don't import.
        skip_errors: Continue on errors.
        update_existing: Update existing records.
        batch_size: Batch size for processing.
        tenant_id: Optional tenant ID.
        user_id: Optional user ID who initiated the import.

    Returns:
        JobProgress with results.
    """
    from .service import DataTransferService

    tracker = get_job_tracker(session)
    job = await tracker.create_job(
        job_type=JobType.IMPORT,
        entity_type=entity_type,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    try:
        await tracker.start_job(job.job_id)

        service = DataTransferService(session)
        result = await service.import_from_bytes(
            data=data,
            entity_type=entity_type,
            format=format,
            validate_only=validate_only,
            skip_errors=skip_errors,
            update_existing=update_existing,
            batch_size=batch_size,
        )

        await tracker.update_progress(
            job.job_id,
            processed=result.processed_rows,
            successful=result.successful_rows,
            failed=result.failed_rows,
            total=result.total_rows,
        )

        await tracker.complete_job(
            job.job_id,
            result_data={
                "import_id": result.import_id,
                "status": result.status,
                "total_rows": result.total_rows,
                "successful_rows": result.successful_rows,
                "failed_rows": result.failed_rows,
                "skipped_rows": result.skipped_rows,
            },
        )

    except Exception as e:
        await tracker.fail_job(job.job_id, str(e))
        logger.exception("Import job failed", extra={"job_id": job.job_id})

    return await tracker.get_job(job.job_id) or job
