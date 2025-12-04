"""SQLAlchemy models for the job management system.

Models:
    Job: Core job entity with full lifecycle tracking
    JobAuditLog: Records every state transition for compliance
    JobProgress: Multi-level progress tracking with ETA
    JobLabel: Key-value labels for filtering and grouping
    JobDependency: Job dependency tracking for DAG execution
    JobWebhook: Per-job webhook subscriptions for notifications

All models use UUID primary keys for distributed system compatibility.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from example_service.core.database.base import Base
from example_service.core.database.enums import JobPriority as JobPriorityEnum
from example_service.core.database.enums import JobStatus as JobStatusEnum
from example_service.infra.tasks.jobs.enums import JobStatus


class Job(Base):
    """Core job entity with full lifecycle tracking.

    Represents a unit of work submitted to the job queue. Tracks the complete
    lifecycle from submission through completion, including retries, pauses,
    and cancellation.

    Key Features:
        - 8-state machine (PENDING → QUEUED → RUNNING → COMPLETED/FAILED)
        - 4-level priority system (LOW, NORMAL, HIGH, URGENT)
        - Parent-child relationships for workflows
        - Timeout enforcement with auto-cancellation
        - Retry tracking with configurable max retries
        - Result storage in PostgreSQL (JSONB)

    Example:
        job = Job(
            tenant_id="tenant-123",
            task_name="process_audio",
            task_args={"audio_url": "s3://bucket/file.wav"},
            priority=JobPriority.HIGH,
            timeout_seconds=3600,
        )
    """

    __tablename__ = "jobs"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Tenant isolation
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Task identification
    task_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Name of the task function"
    )
    task_args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, comment="Task arguments as JSON"
    )

    # State machine
    status: Mapped[str] = mapped_column(
        JobStatusEnum, default="pending", nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(JobPriorityEnum, default="2", nullable=False)

    # Parent job reference (for workflows/pipelines)
    parent_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Parent job ID for workflow hierarchies",
    )

    # Lifecycle timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When job entered queue"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When execution started"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When job completed/failed"
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When job was paused"
    )

    # Timeout and scheduling
    timeout_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Auto-cancel if running longer than this"
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Delayed execution start time"
    )

    # Resource tracking (basic: duration + cost)
    duration_ms: Mapped[float | None] = mapped_column(
        nullable=True, comment="Execution duration in milliseconds"
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0"), comment="Total cost in USD"
    )

    # Results (PostgreSQL only)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Job result data"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if failed"
    )

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current retry attempt number"
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, comment="Maximum retry attempts"
    )

    # Cancellation
    cancel_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Reason for cancellation"
    )

    # Relationships
    audit_logs: Mapped[list[JobAuditLog]] = relationship(
        "JobAuditLog",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobAuditLog.created_at.desc()",
    )
    progress: Mapped[JobProgress | None] = relationship(
        "JobProgress",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )
    labels: Mapped[list[JobLabel]] = relationship(
        "JobLabel",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    webhook_subscriptions: Mapped[list[JobWebhook]] = relationship(
        "JobWebhook",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    dependencies: Mapped[list[JobDependency]] = relationship(
        "JobDependency",
        foreign_keys="JobDependency.job_id",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    dependents: Mapped[list[JobDependency]] = relationship(
        "JobDependency",
        foreign_keys="JobDependency.depends_on_job_id",
        back_populates="depends_on",
    )
    parent: Mapped[Job | None] = relationship(
        "Job",
        remote_side=[id],
        foreign_keys=[parent_job_id],
        back_populates="children",
    )
    children: Mapped[list[Job]] = relationship(
        "Job",
        back_populates="parent",
        foreign_keys=[parent_job_id],
    )

    __table_args__ = (
        # Priority queue ordering (for queued jobs)
        Index(
            "ix_jobs_priority_queued",
            priority.desc(),
            created_at.asc(),
            postgresql_where=(status == JobStatus.QUEUED),
        ),
        # Timeout detection (for running jobs with timeout)
        Index(
            "ix_jobs_running_timeout",
            started_at,
            postgresql_where=((status == JobStatus.RUNNING) & (timeout_seconds.isnot(None))),
        ),
        # TTL cleanup (for terminal jobs)
        Index(
            "ix_jobs_completed_cleanup",
            completed_at,
            postgresql_where=(
                status.in_([JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED])
            ),
        ),
        # Tenant + status queries
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
        # Task name queries
        Index("ix_jobs_task_name_status", "task_name", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Job(id={self.id}, task={self.task_name}, "
            f"status={self.status}, priority={self.priority})>"
        )


class JobAuditLog(Base):
    """Records every state transition for compliance and debugging.

    Creates an immutable audit trail of all job state changes. Each record
    captures the transition details including who/what triggered it and why.

    Use Cases:
        - Regulatory compliance (audit trails)
        - Debugging job failures
        - Analytics on job lifecycle
        - SLA violation detection

    Example:
        audit = JobAuditLog(
            job_id=job.id,
            from_status=JobStatus.RUNNING,
            to_status=JobStatus.FAILED,
            triggered_by="system",
            reason="Timeout exceeded",
        )
    """

    __tablename__ = "job_audit_logs"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Job reference
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Transition details
    from_status: Mapped[JobStatus | None] = mapped_column(
        nullable=True, comment="Previous status (None for creation)"
    )
    to_status: Mapped[JobStatus] = mapped_column(nullable=False, comment="New status")

    # Context
    triggered_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="What triggered the transition: user, system, timeout, dependency",
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="User ID if user-triggered"
    )
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Human-readable reason for transition"
    )
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Additional context data"
    )

    # Timestamp (immutable)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        index=True,
    )

    # Relationship
    job: Mapped[Job] = relationship("Job", back_populates="audit_logs")

    __table_args__ = (
        # Efficient job history queries
        Index("ix_job_audit_job_created", "job_id", "created_at"),
    )

    def __repr__(self) -> str:
        from_str = self.from_status.value if self.from_status else "None"
        return f"<JobAuditLog(job_id={self.job_id}, {from_str} → {self.to_status.value})>"


class JobProgress(Base):
    """Multi-level progress tracking with ETA estimation.

    Provides detailed progress information beyond simple percentage:
    - Stage-level tracking (e.g., "Stage 2 of 5: Processing")
    - Item-level tracking (e.g., "File 23 of 50")
    - ETA estimation based on elapsed time
    - Custom status messages for UI display

    Example:
        progress = JobProgress(
            job_id=job.id,
            percentage=45,
            current_stage="transcription",
            total_stages=3,
            completed_stages=1,
            current_item=23,
            total_items=50,
            message="Transcribing audio file 23 of 50",
        )
    """

    __tablename__ = "job_progress"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Job reference (one-to-one)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Overall progress
    percentage: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="0-100 percentage complete"
    )

    # Stage tracking
    current_stage: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Current stage name"
    )
    total_stages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Total number of stages"
    )
    completed_stages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Completed stages count"
    )

    # Item tracking (e.g., "Processing file 23 of 50")
    current_item: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current item being processed"
    )
    total_items: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Total items to process"
    )

    # ETA estimation
    estimated_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Estimated completion time"
    )

    # Custom UI message
    message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Custom progress message for display"
    )

    # Update tracking
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationship
    job: Mapped[Job] = relationship("Job", back_populates="progress")

    def __repr__(self) -> str:
        return f"<JobProgress(job_id={self.job_id}, {self.percentage}%)>"


class JobLabel(Base):
    """Key-value labels for filtering and grouping jobs.

    Allows attaching arbitrary metadata to jobs for:
    - Filtering (get all jobs with label "campaign=Q4-2024")
    - Grouping (aggregate metrics by label)
    - Bulk operations (cancel all jobs with label "batch=123")

    Example:
        labels = [
            JobLabel(job_id=job.id, key="campaign", value="Q4-2024"),
            JobLabel(job_id=job.id, key="client", value="acme-corp"),
            JobLabel(job_id=job.id, key="priority_reason", value="urgent-deadline"),
        ]
    """

    __tablename__ = "job_labels"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Job reference
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Key-value pair
    key: Mapped[str] = mapped_column(String(100), nullable=False, comment="Label key")
    value: Mapped[str] = mapped_column(String(255), nullable=False, comment="Label value")

    # Relationship
    job: Mapped[Job] = relationship("Job", back_populates="labels")

    __table_args__ = (
        # Efficient label queries
        Index("ix_job_labels_key_value", "key", "value"),
        # One label per key per job
        UniqueConstraint("job_id", "key", name="uq_job_label_key"),
    )

    def __repr__(self) -> str:
        return f"<JobLabel(job_id={self.job_id}, {self.key}={self.value})>"


class JobDependency(Base):
    """Job dependency tracking for DAG execution.

    Allows defining dependencies between jobs:
    - Job B depends on Job A → Job B won't start until Job A completes
    - Supports required (hard) and optional (soft) dependencies
    - Tracks satisfaction status for efficient queuing

    DAG Execution Rules:
        - Jobs with unsatisfied required dependencies stay in PENDING
        - When a job completes, check all dependents for eligibility
        - Soft dependencies don't block but provide ordering hints

    Example:
        # Job B depends on Job A completing successfully
        dep = JobDependency(
            job_id=job_b.id,
            depends_on_job_id=job_a.id,
            required=True,
        )
    """

    __tablename__ = "job_dependencies"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # The job that has the dependency
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The job being depended on
    depends_on_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Dependency type
    required: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        comment="True = hard dependency (blocks), False = soft (ordering hint)",
    )

    # Satisfaction tracking
    satisfied: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="Whether dependency is satisfied"
    )
    satisfied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When dependency was satisfied"
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", foreign_keys=[job_id], back_populates="dependencies")
    depends_on: Mapped[Job] = relationship(
        "Job", foreign_keys=[depends_on_job_id], back_populates="dependents"
    )

    __table_args__ = (
        # Prevent duplicate dependencies
        UniqueConstraint("job_id", "depends_on_job_id", name="uq_job_dependency"),
        # Efficient dependency checks
        Index("ix_job_deps_unsatisfied", "job_id", postgresql_where=(~satisfied)),
    )

    def __repr__(self) -> str:
        status = "satisfied" if self.satisfied else "pending"
        return f"<JobDependency(job={self.job_id} depends_on={self.depends_on_job_id}, {status})>"


class JobWebhook(Base):
    """Per-job webhook subscriptions for state change notifications.

    Allows registering webhooks that fire when job state changes:
    - on_completed: Fire when job completes successfully
    - on_failed: Fire when job fails
    - on_cancelled: Fire when job is cancelled
    - on_progress: Fire on progress updates (debounced)

    Webhook Payload:
        {
            "job_id": "...",
            "event": "completed|failed|cancelled|progress",
            "status": "...",
            "progress": {...} if progress event,
            "result": {...} if completed,
            "error": "..." if failed,
            "timestamp": "..."
        }

    Example:
        webhook = JobWebhook(
            job_id=job.id,
            url="https://example.com/webhook",
            secret="hmac-secret-key",
            on_completed=True,
            on_failed=True,
        )
    """

    __tablename__ = "job_webhooks"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Job reference
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Webhook configuration
    url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="Webhook endpoint URL")
    secret: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="HMAC secret for signature verification"
    )

    # Event triggers
    on_completed: Mapped[bool] = mapped_column(
        nullable=False, default=True, comment="Fire on successful completion"
    )
    on_failed: Mapped[bool] = mapped_column(nullable=False, default=True, comment="Fire on failure")
    on_cancelled: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="Fire on cancellation"
    )
    on_progress: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="Fire on progress updates (debounced)"
    )

    # Delivery tracking
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last delivery attempt"
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last successful delivery"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Consecutive failures"
    )

    # Relationship
    job: Mapped[Job] = relationship("Job", back_populates="webhook_subscriptions")

    def __repr__(self) -> str:
        return f"<JobWebhook(job_id={self.job_id}, url={self.url[:50]}...)>"


__all__ = [
    "Job",
    "JobAuditLog",
    "JobDependency",
    "JobLabel",
    "JobProgress",
    "JobWebhook",
]
