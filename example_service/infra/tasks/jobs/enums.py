"""Job system enumerations.

Defines the state machine and priority levels for the job management system.

State Machine:
    PENDING → QUEUED → RUNNING → COMPLETED
       │        │        │
       │        │        ├→ FAILED → RETRYING → QUEUED
       │        │        │
       ↓        ↓        ↓
    CANCELLED ← ─────── PAUSED → QUEUED (resume)

Priority Levels:
    URGENT (4) > HIGH (3) > NORMAL (2) > LOW (1)
    Higher priority jobs are processed first.
"""

from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    """8-state job lifecycle status.

    States:
        PENDING: Created but not yet queued (dependencies may be unsatisfied)
        QUEUED: In queue waiting for a worker to pick it up
        RUNNING: Currently being executed by a worker
        COMPLETED: Successfully finished
        FAILED: Execution failed after all retries exhausted
        CANCELLED: Cancelled by user or system
        RETRYING: Failed but waiting for retry (backoff period)
        PAUSED: Temporarily suspended by user

    Transition Rules:
        - PENDING → QUEUED: When all dependencies are satisfied
        - QUEUED → RUNNING: When a worker picks up the job
        - RUNNING → COMPLETED: Successful execution
        - RUNNING → FAILED: Failed and max_retries exceeded
        - FAILED → RETRYING: If retry_count < max_retries
        - RETRYING → QUEUED: After backoff delay expires
        - * → CANCELLED: User or system cancellation (from any state)
        - RUNNING → PAUSED: User pause request
        - PAUSED → QUEUED: Resume (immediately or at scheduled time)
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    PAUSED = "paused"

    @classmethod
    def terminal_states(cls) -> set[JobStatus]:
        """Return states that represent job completion (no further transitions)."""
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def active_states(cls) -> set[JobStatus]:
        """Return states where the job is still active/in-progress."""
        return {cls.PENDING, cls.QUEUED, cls.RUNNING, cls.RETRYING, cls.PAUSED}

    @classmethod
    def cancellable_states(cls) -> set[JobStatus]:
        """Return states from which a job can be cancelled."""
        return {cls.PENDING, cls.QUEUED, cls.RUNNING, cls.RETRYING, cls.PAUSED}

    @classmethod
    def pausable_states(cls) -> set[JobStatus]:
        """Return states from which a job can be paused."""
        return {cls.RUNNING}

    def is_terminal(self) -> bool:
        """Check if this status represents a terminal state."""
        return self in self.terminal_states()

    def is_active(self) -> bool:
        """Check if this status represents an active job."""
        return self in self.active_states()


class JobPriority(int, enum.Enum):
    """4-level priority system for job ordering.

    Priority affects queue ordering in the Redis priority queue:
    - Higher priority = processed first
    - Within same priority = FIFO ordering

    Queue Score Formula:
        score = (10 - priority) * 1e12 + timestamp_ms
        This ensures higher priority jobs have lower scores (processed first)
        and equal priority jobs are ordered by submission time.

    Levels:
        LOW (1): Background tasks, can be delayed indefinitely
        NORMAL (2): Standard priority, default for most jobs
        HIGH (3): Important tasks, processed before normal
        URGENT (4): Critical tasks, processed immediately
    """

    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4

    @classmethod
    def default(cls) -> JobPriority:
        """Return the default priority for new jobs."""
        return cls.NORMAL

    def label(self) -> str:
        """Human-readable label for the priority level."""
        return self.name.capitalize()


# Valid state transitions (from_state -> set of valid to_states)
VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.PENDING: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.PAUSED,
    },
    JobStatus.COMPLETED: set(),  # Terminal state
    JobStatus.FAILED: {JobStatus.RETRYING},  # Can retry if retries remaining
    JobStatus.CANCELLED: set(),  # Terminal state
    JobStatus.RETRYING: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.PAUSED: {JobStatus.QUEUED, JobStatus.CANCELLED},
}


def is_valid_transition(from_status: JobStatus, to_status: JobStatus) -> bool:
    """Check if a state transition is valid.

    Args:
        from_status: Current job status
        to_status: Desired new status

    Returns:
        True if the transition is allowed, False otherwise
    """
    return to_status in VALID_TRANSITIONS.get(from_status, set())


__all__ = [
    "VALID_TRANSITIONS",
    "JobPriority",
    "JobStatus",
    "is_valid_transition",
]
