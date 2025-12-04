"""Job audit logging for state transition tracking.

Records every state transition in the job lifecycle for:
- Regulatory compliance (audit trails)
- Debugging job failures
- Analytics on job lifecycle
- SLA violation detection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from example_service.infra.tasks.jobs.enums import JobStatus, is_valid_transition
from example_service.infra.tasks.jobs.models import JobAuditLog

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.tasks.jobs.models import Job

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: JobStatus | None,
        to_status: JobStatus,
        job_id: UUID | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.job_id = job_id
        super().__init__(
            f"Invalid transition from {from_status} to {to_status}"
            + (f" for job {job_id}" if job_id else "")
        )


class AuditLogger:
    """Records state transitions in the job_audit_logs table.

    Usage:
        audit = AuditLogger(session)

        # Log a transition
        await audit.log_transition(
            job=job,
            to_status=JobStatus.RUNNING,
            triggered_by="system",
        )

        # Get audit history
        history = await audit.get_history(job_id)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the audit logger.

        Args:
            session: SQLAlchemy async session for database operations
        """
        self._session = session

    async def log_transition(
        self,
        job: Job,
        to_status: JobStatus,
        triggered_by: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
        extra_data: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> JobAuditLog:
        """Log a state transition for a job.

        Args:
            job: The job being transitioned
            to_status: New status to transition to
            triggered_by: What triggered the transition ("user", "system", "timeout", etc.)
            actor_id: User ID if triggered by a user
            reason: Human-readable reason for the transition
            extra_data: Additional context data
            validate: Whether to validate the transition is allowed

        Returns:
            The created audit log entry

        Raises:
            InvalidTransitionError: If validate=True and transition is invalid
        """
        from_status_str = job.status
        from_status = JobStatus(from_status_str) if from_status_str else None

        # Validate transition if requested
        if validate and from_status is not None and not is_valid_transition(from_status, to_status):
            raise InvalidTransitionError(from_status, to_status, job.id)

        # Create audit log entry
        audit_log = JobAuditLog(
            job_id=job.id,
            from_status=from_status,
            to_status=to_status,
            triggered_by=triggered_by,
            actor_id=actor_id,
            reason=reason,
            extra_data=extra_data,
        )

        self._session.add(audit_log)

        logger.debug(
            "Logged job state transition",
            extra={
                "job_id": str(job.id),
                "from_status": from_status.value if from_status else None,
                "to_status": to_status.value,
                "triggered_by": triggered_by,
            },
        )

        return audit_log

    async def log_creation(
        self,
        job: Job,
        *,
        actor_id: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> JobAuditLog:
        """Log job creation (initial state).

        Args:
            job: The newly created job
            actor_id: User ID who created the job
            extra_data: Additional context data

        Returns:
            The created audit log entry
        """
        audit_log = JobAuditLog(
            job_id=job.id,
            from_status=None,  # No previous status for creation
            to_status=job.status,
            triggered_by="user" if actor_id else "system",
            actor_id=actor_id,
            reason="Job created",
            extra_data=extra_data,
        )

        self._session.add(audit_log)

        logger.debug(
            "Logged job creation",
            extra={
                "job_id": str(job.id),
                "status": job.status,
                "actor_id": actor_id,
            },
        )

        return audit_log

    async def get_history(
        self,
        job_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobAuditLog]:
        """Get audit history for a job.

        Args:
            job_id: Job ID to get history for
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            List of audit log entries, newest first
        """
        result = await self._session.execute(
            select(JobAuditLog)
            .where(JobAuditLog.job_id == job_id)
            .order_by(JobAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_last_transition(
        self,
        job_id: UUID,
    ) -> JobAuditLog | None:
        """Get the most recent transition for a job.

        Args:
            job_id: Job ID to get last transition for

        Returns:
            Most recent audit log entry, or None if none found
        """
        result = await self._session.execute(
            select(JobAuditLog)
            .where(JobAuditLog.job_id == job_id)
            .order_by(JobAuditLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_transitions(
        self,
        job_id: UUID,
        *,
        from_status: JobStatus | None = None,
        to_status: JobStatus | None = None,
        since: datetime | None = None,
    ) -> int:
        """Count transitions matching criteria.

        Args:
            job_id: Job ID to count transitions for
            from_status: Filter by source status
            to_status: Filter by destination status
            since: Only count transitions after this time

        Returns:
            Number of matching transitions
        """
        from sqlalchemy import func

        query = select(func.count()).select_from(JobAuditLog).where(JobAuditLog.job_id == job_id)

        if from_status is not None:
            query = query.where(JobAuditLog.from_status == from_status)
        if to_status is not None:
            query = query.where(JobAuditLog.to_status == to_status)
        if since is not None:
            query = query.where(JobAuditLog.created_at >= since)

        result = await self._session.execute(query)
        return result.scalar_one()


__all__ = [
    "AuditLogger",
    "InvalidTransitionError",
]
