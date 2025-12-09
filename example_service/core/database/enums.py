"""Centralized PostgreSQL ENUM type definitions.

This module provides all PostgreSQL ENUM types used across the application.
By centralizing enum definitions here, we enable alembic-postgresql-enum to
automatically generate enum creation and evolution migrations.

Usage in models:
    from example_service.core.database.enums import FileStatus

    class File(Base):
        status: Mapped[str] = mapped_column(FileStatus, nullable=False)

Note: These are SQLAlchemy ENUM types, not Python enums. Import the Python
enums from their respective modules for application logic.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

# =============================================================================
# File Enums
# =============================================================================

FileStatus = ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    "deleted",
    name="filestatus",
    create_type=False,  # Let alembic-postgresql-enum handle creation
)


# =============================================================================
# Email Enums
# =============================================================================

EmailProviderType = ENUM(
    "smtp",
    "aws_ses",
    "sendgrid",
    "mailgun",
    "console",
    "file",
    name="emailprovidertype",
    create_type=False,
)

DeliveryStatus = ENUM(
    "pending",
    "delivered",
    "failed",
    "retrying",
    name="deliverystatus",
    create_type=False,
)


# =============================================================================
# AI Enums
# =============================================================================

AIProviderType = ENUM(
    "LLM",
    "TRANSCRIPTION",
    "EMBEDDING",
    "IMAGE",
    "PII_REDACTION",
    name="aiprovidertype",
    create_type=False,
)

AIJobType = ENUM(
    "TRANSCRIPTION",
    "PII_REDACTION",
    "SUMMARY",
    "SENTIMENT",
    "COACHING",
    "FULL_ANALYSIS",
    name="aijobtype",
    create_type=False,
)

AIJobStatus = ENUM(
    "PENDING",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    name="aijobstatus",
    create_type=False,
)


# =============================================================================
# AI Agent Enums
# =============================================================================

AIAgentRunStatus = ENUM(
    "pending",
    "running",
    "paused",
    "waiting_input",
    "completed",
    "failed",
    "cancelled",
    "timeout",
    name="aiagentrunstatus",
    create_type=False,
)

AIAgentStepType = ENUM(
    "llm_call",
    "tool_call",
    "human_input",
    "checkpoint",
    "branch",
    "parallel",
    "subagent",
    name="aiagentsteptype",
    create_type=False,
)

AIAgentStepStatus = ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "retrying",
    name="aiagentstepstatus",
    create_type=False,
)

AIAgentMessageRole = ENUM(
    "system",
    "user",
    "assistant",
    "tool",
    "function",
    name="aiagentmessagerole",
    create_type=False,
)


# =============================================================================
# Job System Enums
# =============================================================================

JobStatus = ENUM(
    "pending",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "retrying",
    "paused",
    name="jobstatus",
    create_type=False,
)

JobPriority = ENUM(
    "1",  # LOW
    "2",  # NORMAL
    "3",  # HIGH
    "4",  # URGENT
    name="jobpriority",
    create_type=False,
)


# =============================================================================
# Feature Flag Enums
# =============================================================================

FlagStatus = ENUM(
    "enabled",
    "disabled",
    "percentage",
    "targeted",
    name="flagstatus",
    create_type=False,
)


# =============================================================================
# Audit Enums
# =============================================================================

AuditAction = ENUM(
    "create",
    "read",
    "update",
    "delete",
    "bulk_create",
    "bulk_update",
    "bulk_delete",
    "export",
    "import",
    "login",
    "logout",
    "login_failed",
    "password_change",
    "token_refresh",
    "permission_denied",
    "acl_check",
    "archive",
    "restore",
    "purge",
    name="auditaction",
    create_type=False,
)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AIAgentMessageRole",
    "AIAgentRunStatus",
    "AIAgentStepStatus",
    "AIAgentStepType",
    "AIJobStatus",
    "AIJobType",
    "AIProviderType",
    "AuditAction",
    "DeliveryStatus",
    "EmailProviderType",
    "FileStatus",
    "FlagStatus",
    "JobPriority",
    "JobStatus",
]
