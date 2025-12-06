"""High-level job orchestration with full lifecycle management.

The JobManager provides a unified interface for:
- Submitting jobs with priorities, dependencies, labels
- Updating job state with audit logging
- Managing job lifecycle (pause, resume, cancel)
- Updating progress
- Bulk operations
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from example_service.core.settings.jobs import get_job_settings
from example_service.infra.tasks.jobs.audit import AuditLogger
from example_service.infra.tasks.jobs.enums import JobPriority, JobStatus
from example_service.infra.tasks.jobs.models import (
    Job,
    JobDependency,
    JobLabel,
    JobProgress,
    JobWebhook,
)

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class JobNotFoundError(Exception):
    """Raised when a job is not found."""

    def __init__(self, job_id: UUID) -> None:
        self.job_id = job_id
        super().__init__(f"Job {job_id} not found")


class JobManager:
    """High-level job orchestration with full lifecycle management.

    Usage:
        manager = JobManager(session)

        # Submit a job
        job = await manager.submit(
            tenant_id="tenant-123",
            task_name="process_audio",
            args={"audio_url": "..."},
            priority=JobPriority.HIGH,
            timeout_seconds=3600,
            labels={"campaign": "Q4-2024"},
        )

        # Update progress
        await manager.update_progress(
            job_id=job.id,
            percentage=50,
            stage="transcription",
            message="Transcribing audio...",
        )

        # Cancel a job
        await manager.cancel(job.id, reason="User requested")
    """

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis | None = None,
    ) -> None:
        """Initialize the job manager.

        Args:
            session: SQLAlchemy async session for database operations
            redis: Optional Redis client for priority queue operations
        """
        self._session = session
        self._redis = redis
        self._audit = AuditLogger(session)
        self._settings = get_job_settings()

    # =========================================================================
    # Job Submission
    # =========================================================================

    async def submit(
        self,
        tenant_id: str,
        task_name: str,
        args: dict[str, Any],
        *,
        priority: JobPriority = JobPriority.NORMAL,
        depends_on: list[UUID] | None = None,
        labels: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        webhook_url: str | None = None,
        scheduled_at: datetime | None = None,
        max_retries: int | None = None,
        parent_job_id: UUID | None = None,
        actor_id: str | None = None,
    ) -> Job:
        """Submit a new job for processing.

        Args:
            tenant_id: Tenant identifier
            task_name: Name of the task to execute
            args: Task arguments
            priority: Job priority level
            depends_on: List of job IDs this job depends on
            labels: Key-value labels for filtering
            timeout_seconds: Auto-cancel if running longer than this
            webhook_url: URL to notify on state changes
            scheduled_at: Delayed execution start time
            max_retries: Maximum retry attempts (default from settings)
            parent_job_id: Parent job for workflow hierarchies
            actor_id: User ID who submitted the job

        Returns:
            The created job
        """
        # Create the job
        job = Job(
            tenant_id=tenant_id,
            task_name=task_name,
            task_args=args,
            priority=priority,
            status=JobStatus.PENDING,
            timeout_seconds=timeout_seconds or self._settings.default_timeout_seconds,
            scheduled_at=scheduled_at,
            max_retries=max_retries or self._settings.default_max_retries,
            parent_job_id=parent_job_id,
        )
        self._session.add(job)
        await self._session.flush()  # Get the job ID

        # Add labels if provided
        if labels:
            for key, value in labels.items():
                label = JobLabel(job_id=job.id, key=key, value=value)
                self._session.add(label)

        # Add dependencies if provided
        if depends_on:
            for dep_job_id in depends_on:
                dependency = JobDependency(
                    job_id=job.id,
                    depends_on_job_id=dep_job_id,
                    required=True,
                )
                self._session.add(dependency)

        # Add webhook if provided
        if webhook_url:
            webhook = JobWebhook(
                job_id=job.id,
                url=webhook_url,
                on_completed=True,
                on_failed=True,
            )
            self._session.add(webhook)

        # Create initial progress record
        progress = JobProgress(
            job_id=job.id,
            percentage=0,
            total_stages=1,
        )
        self._session.add(progress)

        # Log creation
        await self._audit.log_creation(
            job,
            actor_id=actor_id,
            extra_data={"task_name": task_name, "priority": priority.name},
        )

        # Check if job can be immediately queued (no dependencies)
        if not depends_on:
            await self._transition_to_queued(job, actor_id=actor_id)

        logger.info(
            "Job submitted",
            extra={
                "job_id": str(job.id),
                "tenant_id": tenant_id,
                "task_name": task_name,
                "priority": priority.name,
                "status": job.status,
            },
        )

        return job

    async def submit_bulk(
        self,
        jobs_data: list[dict[str, Any]],
        *,
        actor_id: str | None = None,
    ) -> list[Job]:
        """Submit multiple jobs atomically.

        Args:
            jobs_data: List of job data dicts (same keys as submit())
            actor_id: User ID who submitted the jobs

        Returns:
            List of created jobs

        Raises:
            ValueError: If too many jobs in single request
        """
        if len(jobs_data) > self._settings.max_bulk_submit_size:
            raise ValueError(
                f"Cannot submit more than {self._settings.max_bulk_submit_size} "
                f"jobs at once (got {len(jobs_data)})"
            )

        jobs = []
        for data in jobs_data:
            job = await self.submit(
                **data,
                actor_id=actor_id,
            )
            jobs.append(job)

        logger.info(
            "Bulk job submission completed",
            extra={"count": len(jobs), "actor_id": actor_id},
        )

        return jobs

    # =========================================================================
    # State Transitions
    # =========================================================================

    async def _transition_to_queued(
        self,
        job: Job,
        *,
        actor_id: str | None = None,
    ) -> None:
        """Transition a job to QUEUED status.

        Args:
            job: Job to transition
            actor_id: User ID if user-triggered
        """
        if job.status != JobStatus.PENDING:
            return  # Already queued or further along

        job.status = JobStatus.QUEUED
        job.queued_at = datetime.now(UTC)

        await self._audit.log_transition(
            job,
            to_status=JobStatus.QUEUED,
            triggered_by="system",
            actor_id=actor_id,
            reason="Dependencies satisfied" if job.dependencies else "No dependencies",
        )

    async def mark_running(
        self,
        job_id: UUID,
        *,
        worker_id: str | None = None,
    ) -> Job:
        """Mark a job as running (called by worker).

        Args:
            job_id: Job ID
            worker_id: Worker identifier

        Returns:
            Updated job

        Raises:
            JobNotFoundError: If job not found
            InvalidTransitionError: If transition not allowed
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        await self._audit.log_transition(
            job,
            to_status=JobStatus.RUNNING,
            triggered_by="system",
            extra_data={"worker_id": worker_id} if worker_id else None,
        )

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        return job

    async def mark_completed(
        self,
        job_id: UUID,
        *,
        result_data: dict[str, Any] | None = None,
        cost_usd: Decimal | None = None,
    ) -> Job:
        """Mark a job as completed.

        Args:
            job_id: Job ID
            result_data: Job result data
            cost_usd: Total cost of the job

        Returns:
            Updated job
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        now = datetime.now(UTC)
        duration_ms = None
        if job.started_at:
            duration_ms = (now - job.started_at).total_seconds() * 1000

        await self._audit.log_transition(
            job,
            to_status=JobStatus.COMPLETED,
            triggered_by="system",
            extra_data={"duration_ms": duration_ms},
        )

        job.status = JobStatus.COMPLETED
        job.completed_at = now
        job.duration_ms = duration_ms
        job.result_data = result_data
        if cost_usd is not None:
            job.cost_usd = cost_usd

        # Update progress to 100%
        if job.progress:
            job.progress.percentage = 100
            job.progress.message = "Completed"

        # Notify dependents
        await self._notify_dependents(job)

        return job

    async def mark_failed(
        self,
        job_id: UUID,
        *,
        error_message: str,
        should_retry: bool = True,
    ) -> Job:
        """Mark a job as failed.

        Args:
            job_id: Job ID
            error_message: Error description
            should_retry: Whether to retry if retries remaining

        Returns:
            Updated job
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        now = datetime.now(UTC)
        duration_ms = None
        if job.started_at:
            duration_ms = (now - job.started_at).total_seconds() * 1000

        # Check if we should retry
        if should_retry and job.retry_count < job.max_retries:
            # Transition to RETRYING
            await self._audit.log_transition(
                job,
                to_status=JobStatus.RETRYING,
                triggered_by="system",
                reason=f"Retry {job.retry_count + 1}/{job.max_retries}: {error_message}",
            )
            job.status = JobStatus.RETRYING
            job.retry_count += 1
            job.error_message = error_message
        else:
            # Final failure
            await self._audit.log_transition(
                job,
                to_status=JobStatus.FAILED,
                triggered_by="system",
                reason=error_message,
                extra_data={"retry_count": job.retry_count, "max_retries": job.max_retries},
            )
            job.status = JobStatus.FAILED
            job.completed_at = now
            job.duration_ms = duration_ms
            job.error_message = error_message

            # Notify dependents (with failure)
            await self._notify_dependents(job)

        return job

    async def cancel(
        self,
        job_id: UUID,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> bool:
        """Cancel a job.

        Args:
            job_id: Job ID
            reason: Cancellation reason
            actor_id: User ID if user-triggered

        Returns:
            True if cancelled, False if already terminal
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        if JobStatus(job.status).is_terminal():
            return False

        if job.status not in JobStatus.cancellable_states():
            return False

        await self._audit.log_transition(
            job,
            to_status=JobStatus.CANCELLED,
            triggered_by="user" if actor_id else "system",
            actor_id=actor_id,
            reason=reason,
        )

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        job.cancel_reason = reason

        # Notify dependents (with cancellation)
        await self._notify_dependents(job)

        logger.info(
            "Job cancelled",
            extra={
                "job_id": str(job_id),
                "reason": reason,
                "actor_id": actor_id,
            },
        )

        return True

    async def cancel_bulk(
        self,
        job_ids: list[UUID],
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> dict[UUID, bool]:
        """Cancel multiple jobs.

        Args:
            job_ids: List of job IDs to cancel
            reason: Cancellation reason
            actor_id: User ID if user-triggered

        Returns:
            Dict mapping job_id to success status
        """
        results = {}
        for job_id in job_ids:
            try:
                results[job_id] = await self.cancel(job_id, reason, actor_id=actor_id)
            except JobNotFoundError:
                results[job_id] = False
        return results

    async def pause(
        self,
        job_id: UUID,
        *,
        resume_at: datetime | None = None,
        actor_id: str | None = None,
    ) -> bool:
        """Pause a running job.

        Args:
            job_id: Job ID
            resume_at: When to auto-resume (optional)
            actor_id: User ID

        Returns:
            True if paused, False if not pausable
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        if job.status not in JobStatus.pausable_states():
            return False

        await self._audit.log_transition(
            job,
            to_status=JobStatus.PAUSED,
            triggered_by="user" if actor_id else "system",
            actor_id=actor_id,
            extra_data={"resume_at": resume_at.isoformat()} if resume_at else None,
        )

        job.status = JobStatus.PAUSED
        job.paused_at = datetime.now(UTC)

        return True

    async def resume(
        self,
        job_id: UUID,
        *,
        actor_id: str | None = None,
    ) -> bool:
        """Resume a paused job.

        Args:
            job_id: Job ID
            actor_id: User ID

        Returns:
            True if resumed, False if not paused
        """
        job = await self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        if job.status != JobStatus.PAUSED:
            return False

        await self._audit.log_transition(
            job,
            to_status=JobStatus.QUEUED,
            triggered_by="user" if actor_id else "system",
            actor_id=actor_id,
            reason="Resumed from pause",
        )

        job.status = JobStatus.QUEUED
        job.paused_at = None
        job.queued_at = datetime.now(UTC)

        return True

    # =========================================================================
    # Progress Tracking
    # =========================================================================

    async def update_progress(
        self,
        job_id: UUID,
        percentage: int,
        *,
        stage: str | None = None,
        current_item: int | None = None,
        total_items: int | None = None,
        message: str | None = None,
        estimated_completion: datetime | None = None,
    ) -> JobProgress | None:
        """Update job progress.

        Args:
            job_id: Job ID
            percentage: Progress percentage (0-100)
            stage: Current stage name
            current_item: Current item being processed
            total_items: Total items to process
            message: Custom progress message
            estimated_completion: Estimated completion time

        Returns:
            Updated progress record, or None if job not found
        """
        result = await self._session.execute(
            select(JobProgress).where(JobProgress.job_id == job_id)
        )
        progress = result.scalar_one_or_none()

        if progress is None:
            return None

        progress.percentage = min(100, max(0, percentage))
        if stage is not None:
            progress.current_stage = stage
        if current_item is not None:
            progress.current_item = current_item
        if total_items is not None:
            progress.total_items = total_items
        if message is not None:
            progress.message = message
        if estimated_completion is not None:
            progress.estimated_completion = estimated_completion

        return progress

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get(
        self,
        job_id: UUID,
        *,
        include_relations: bool = False,
    ) -> Job | None:
        """Get a job by ID.

        Args:
            job_id: Job ID
            include_relations: Whether to eagerly load relations

        Returns:
            Job or None if not found
        """
        query = select(Job).where(Job.id == job_id)

        if include_relations:
            query = query.options(
                selectinload(Job.audit_logs),
                selectinload(Job.progress),
                selectinload(Job.labels),
                selectinload(Job.dependencies),
                selectinload(Job.webhook_subscriptions),
            )

        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_labels(
        self,
        tenant_id: str,
        labels: dict[str, str],
        *,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """Get jobs matching label criteria.

        Args:
            tenant_id: Tenant ID
            labels: Labels to match (all must match)
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of matching jobs
        """
        query = select(Job).where(Job.tenant_id == tenant_id)

        if status is not None:
            query = query.where(Job.status == status)

        # Join labels and filter
        for key, value in labels.items():
            label_subquery = select(JobLabel.job_id).where(
                JobLabel.key == key, JobLabel.value == value
            )
            query = query.where(Job.id.in_(label_subquery))

        query = query.limit(limit)

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_jobs(
        self,
        tenant_id: str,
        *,
        status: JobStatus | list[JobStatus] | None = None,
        task_name: str | None = None,
        priority: JobPriority | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        """List jobs with filters.

        Args:
            tenant_id: Tenant ID
            status: Filter by status(es)
            task_name: Filter by task name
            priority: Filter by priority
            limit: Maximum results
            offset: Number to skip

        Returns:
            List of jobs
        """
        query = select(Job).where(Job.tenant_id == tenant_id)

        if status is not None:
            if isinstance(status, list):
                query = query.where(Job.status.in_(status))
            else:
                query = query.where(Job.status == status)

        if task_name is not None:
            query = query.where(Job.task_name == task_name)

        if priority is not None:
            query = query.where(Job.priority == priority)

        query = query.order_by(Job.created_at.desc()).limit(limit).offset(offset)

        result = await self._session.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # Dependency Management
    # =========================================================================

    async def _notify_dependents(self, job: Job) -> None:
        """Notify dependent jobs that this job has completed.

        Args:
            job: The job that completed
        """
        # Find all jobs that depend on this one
        result = await self._session.execute(
            select(JobDependency).where(
                JobDependency.depends_on_job_id == job.id,
                JobDependency.satisfied == False,  # noqa: E712
            )
        )
        dependencies = list(result.scalars().all())

        for dep in dependencies:
            # Mark as satisfied (or failed if parent failed)
            if job.status == JobStatus.COMPLETED:
                dep.satisfied = True
                dep.satisfied_at = datetime.now(UTC)
            elif job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                # If required dependency failed, cancel the dependent job
                if dep.required:
                    dependent_job = await self.get(dep.job_id)
                    if dependent_job and dependent_job.status == JobStatus.PENDING.value:
                        await self.cancel(
                            dep.job_id,
                            f"Required dependency {job.id} {job.status}",
                        )

        # Check if any pending jobs now have all dependencies satisfied
        await self._check_dependencies_satisfied()

    async def _check_dependencies_satisfied(self) -> None:
        """Check for pending jobs with all dependencies satisfied."""
        # Find pending jobs with dependencies
        result = await self._session.execute(
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .options(selectinload(Job.dependencies))
            .limit(self._settings.dependency_check_batch_size)
        )
        pending_jobs = list(result.scalars().all())

        for job in pending_jobs:
            if not job.dependencies:
                continue

            # Check if all required dependencies are satisfied
            all_satisfied = all(dep.satisfied for dep in job.dependencies if dep.required)
            if all_satisfied:
                await self._transition_to_queued(job)


__all__ = [
    "JobManager",
    "JobNotFoundError",
]
