"""Job management system for background task orchestration.

This package provides a comprehensive job management system with:
- 8-state lifecycle machine (PENDING → QUEUED → RUNNING → COMPLETED/FAILED)
- 4-level priority queue (LOW, NORMAL, HIGH, URGENT)
- Job dependencies for DAG-style workflows
- Audit trail for compliance and debugging
- Multi-level progress tracking with ETA
- Per-job webhook notifications
- Timeout enforcement and auto-cancellation
- TTL-based cleanup of old results

Components:
    enums: JobStatus, JobPriority, and transition validation
    models: SQLAlchemy models (Job, JobAuditLog, JobProgress, etc.)
    manager: High-level JobManager for orchestration
    priority_queue: Redis-backed priority queue
    dependencies: DAG resolution for job dependencies
    progress: Progress tracking utilities
    audit: State transition logging
    webhooks: Webhook notification delivery
    timeout: Timeout enforcement
    cleanup: TTL-based cleanup

Usage:
    from example_service.infra.tasks.jobs import JobManager, JobStatus, JobPriority

    # Create manager
    manager = JobManager(session, redis)

    # Submit a job
    job = await manager.submit(
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

    # Check dependencies
    await manager.submit(
        task_name="analyze",
        args={"job_id": str(job.id)},
        depends_on=[job.id],  # Wait for first job
    )
"""

from example_service.infra.tasks.jobs.audit import AuditLogger, InvalidTransitionError
from example_service.infra.tasks.jobs.enums import (
    VALID_TRANSITIONS,
    JobPriority,
    JobStatus,
    is_valid_transition,
)
from example_service.infra.tasks.jobs.manager import JobManager, JobNotFoundError
from example_service.infra.tasks.jobs.models import (
    Job,
    JobAuditLog,
    JobDependency,
    JobLabel,
    JobProgress,
    JobWebhook,
)

__all__ = [
    "VALID_TRANSITIONS",
    # Audit
    "AuditLogger",
    "InvalidTransitionError",
    # Models
    "Job",
    "JobAuditLog",
    "JobDependency",
    "JobLabel",
    # Manager
    "JobManager",
    "JobNotFoundError",
    # Enums
    "JobPriority",
    "JobProgress",
    "JobStatus",
    "JobWebhook",
    "is_valid_transition",
]
