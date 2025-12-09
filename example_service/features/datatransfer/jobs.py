"""Background job processing for data transfer operations.

Provides async background job execution with progress tracking
for long-running export and import operations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import ExportRequest, ImportFormat

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """Status of a background job."""

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
    """Progress information for a background job."""

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
    """Tracks background job progress.

    Thread-safe in-memory job tracker. For production, consider
    using Redis or a database for persistence across restarts.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobProgress] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        job_type: JobType,
        entity_type: str,
        total_records: int = 0,
    ) -> JobProgress:
        """Create a new job and return its progress tracker.

        Args:
            job_type: Type of job (export or import).
            entity_type: Entity type being processed.
            total_records: Total number of records (if known).

        Returns:
            JobProgress instance for tracking.
        """
        job_id = str(uuid.uuid4())
        job = JobProgress(
            job_id=job_id,
            job_type=job_type,
            entity_type=entity_type,
            total_records=total_records,
        )

        async with self._lock:
            self._jobs[job_id] = job

        logger.info(
            "Created background job",
            extra={
                "job_id": job_id,
                "job_type": job_type,
                "entity_type": entity_type,
            },
        )

        return job

    async def start_job(self, job_id: str) -> None:
        """Mark a job as started.

        Args:
            job_id: ID of the job to start.
        """
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = JobStatus.RUNNING
                self._jobs[job_id].started_at = datetime.now(UTC)

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
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.processed_records = processed
                job.successful_records = successful
                job.failed_records = failed
                if total is not None:
                    job.total_records = total

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
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                if result_data:
                    job.result_data = result_data

        logger.info(
            "Job completed",
            extra={
                "job_id": job_id,
                "elapsed_seconds": self._jobs.get(job_id, JobProgress(job_id=job_id, job_type=JobType.EXPORT)).elapsed_seconds,
            },
        )

    async def fail_job(self, job_id: str, error_message: str) -> None:
        """Mark a job as failed.

        Args:
            job_id: ID of the job.
            error_message: Error message describing the failure.
        """
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = error_message

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
        async with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]
            if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(UTC)
                return True

            return False

    async def get_job(self, job_id: str) -> JobProgress | None:
        """Get job progress by ID.

        Args:
            job_id: ID of the job.

        Returns:
            JobProgress if found, None otherwise.
        """
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[JobProgress]:
        """List jobs with optional filtering.

        Args:
            job_type: Filter by job type.
            status: Filter by status.
            limit: Maximum number of jobs to return.

        Returns:
            List of matching jobs.
        """
        async with self._lock:
            jobs = list(self._jobs.values())

        if job_type:
            jobs = [j for j in jobs if j.job_type == job_type]
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Sort by start time descending (newest first)
        jobs.sort(key=lambda j: j.started_at or datetime.min.replace(tzinfo=UTC), reverse=True)

        return jobs[:limit]

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Remove completed jobs older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for completed jobs.

        Returns:
            Number of jobs removed.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        removed = 0

        async with self._lock:
            to_remove = []
            for job_id, job in self._jobs.items():
                if job.completed_at and job.completed_at < cutoff:
                    to_remove.append(job_id)

            for job_id in to_remove:
                del self._jobs[job_id]
                removed += 1

        if removed > 0:
            logger.info("Cleaned up old jobs", extra={"removed_count": removed})

        return removed


# Global job tracker instance
_job_tracker: JobTracker | None = None


def get_job_tracker() -> JobTracker:
    """Get the global job tracker instance.

    Returns:
        JobTracker singleton instance.
    """
    global _job_tracker
    if _job_tracker is None:
        _job_tracker = JobTracker()
    return _job_tracker


async def run_export_job(
    session: AsyncSession,
    request: ExportRequest,
    tenant_id: str | None = None,
) -> JobProgress:
    """Run an export as a background job with progress tracking.

    Args:
        session: Database session.
        request: Export request.
        tenant_id: Optional tenant ID.

    Returns:
        JobProgress with results.
    """
    from .service import DataTransferService

    tracker = get_job_tracker()
    job = await tracker.create_job(
        job_type=JobType.EXPORT,
        entity_type=request.entity_type,
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

    Returns:
        JobProgress with results.
    """
    from .service import DataTransferService

    tracker = get_job_tracker()
    job = await tracker.create_job(
        job_type=JobType.IMPORT,
        entity_type=entity_type,
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
