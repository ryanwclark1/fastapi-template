"""Database models for email configuration.

Models:
- EmailConfig: Per-tenant email provider configuration
- EmailUsageLog: Cost and usage metrics for email operations
- EmailAuditLog: Privacy-compliant audit trail for sent emails
"""

from __future__ import annotations

from datetime import UTC, datetime
import enum
import os
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database.base import (
    Base,
    UserAuditMixin,
    UUIDv7TimestampedBase,
)
from example_service.core.database.enums import (
    EmailProviderType as EmailProviderTypeEnum,
)
from example_service.core.database.types import EncryptedString
from example_service.core.models.tenant import Tenant
from example_service.core.models.user import User
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(Tenant, User)


def _get_email_encryption_key() -> str | None:
    """Get email encryption key from environment.

    This function is called at class definition time, so the key must be
    available in the environment when the module is imported.

    For production, ensure EMAIL_ENCRYPTION_KEY is set before starting the app.
    Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    return os.getenv("EMAIL_ENCRYPTION_KEY")


class EmailProviderType(str, enum.Enum):
    """Email provider types."""

    SMTP = "smtp"
    AWS_SES = "aws_ses"
    SENDGRID = "sendgrid"
    MAILGUN = "mailgun"
    CONSOLE = "console"  # Development only
    FILE = "file"  # Testing only


class EmailConfig(UUIDv7TimestampedBase, UserAuditMixin):
    """Tenant-specific email provider configuration.

    Allows tenants to override default email providers and credentials.
    All sensitive credentials are encrypted at rest using Fernet encryption.

    Examples:
        # Tenant uses their own SMTP server
        EmailConfig(
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.tenant.com",
            smtp_port=587,
            smtp_username="user@tenant.com",
            smtp_password="encrypted-password",  # Auto-encrypted
            is_active=True
        )

        # Tenant uses SendGrid
        EmailConfig(
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SENDGRID,
            api_key="encrypted-sendgrid-key",  # Auto-encrypted
            from_email="noreply@tenant.com"
        )
    """

    __tablename__ = "email_configs"

    tenant_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider_type: Mapped[str] = mapped_column(
        EmailProviderTypeEnum,
        nullable=False,
        comment="Email provider type (smtp, aws_ses, sendgrid, mailgun, console, file)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Whether this config is active",
    )

    # SMTP Configuration
    smtp_host: Mapped[str | None] = mapped_column(
        String(255), comment="SMTP server hostname",
    )
    smtp_port: Mapped[int | None] = mapped_column(
        Integer, comment="SMTP server port (587 for TLS, 465 for SSL)",
    )
    smtp_username: Mapped[str | None] = mapped_column(
        String(255), comment="SMTP authentication username",
    )
    smtp_password: Mapped[str | None] = mapped_column(
        EncryptedString(key=_get_email_encryption_key(), max_length=500),
        comment="SMTP authentication password (encrypted)",
    )
    smtp_use_tls: Mapped[bool | None] = mapped_column(
        Boolean, comment="Use STARTTLS (port 587)",
    )
    smtp_use_ssl: Mapped[bool | None] = mapped_column(
        Boolean, comment="Use implicit SSL (port 465)",
    )

    # AWS SES Configuration
    aws_region: Mapped[str | None] = mapped_column(
        String(50), comment="AWS region for SES (e.g., us-east-1)",
    )
    aws_access_key: Mapped[str | None] = mapped_column(
        EncryptedString(key=_get_email_encryption_key(), max_length=500),
        comment="AWS access key ID (encrypted)",
    )
    aws_secret_key: Mapped[str | None] = mapped_column(
        EncryptedString(key=_get_email_encryption_key(), max_length=500),
        comment="AWS secret access key (encrypted)",
    )
    aws_configuration_set: Mapped[str | None] = mapped_column(
        String(255), comment="AWS SES configuration set name for tracking",
    )

    # SendGrid/Mailgun API Configuration
    api_key: Mapped[str | None] = mapped_column(
        EncryptedString(key=_get_email_encryption_key(), max_length=500),
        comment="API key for SendGrid/Mailgun (encrypted)",
    )
    api_endpoint: Mapped[str | None] = mapped_column(
        String(255), comment="Custom API endpoint (for Mailgun EU, etc.)",
    )

    # Sender Configuration
    from_email: Mapped[str | None] = mapped_column(
        String(255), comment="Default sender email address",
    )
    from_name: Mapped[str | None] = mapped_column(
        String(255), comment="Default sender display name",
    )
    reply_to: Mapped[str | None] = mapped_column(
        String(255), comment="Default reply-to address",
    )

    # Rate Limiting (per-tenant overrides)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(
        Integer, comment="Max emails per minute (None = use system default)",
    )
    rate_limit_per_hour: Mapped[int | None] = mapped_column(
        Integer, comment="Max emails per hour (None = use system default)",
    )
    daily_quota: Mapped[int | None] = mapped_column(
        Integer, comment="Max emails per day (None = unlimited)",
    )

    # Cost Configuration
    cost_per_email_usd: Mapped[float | None] = mapped_column(
        Float, comment="Cost per email in USD for billing calculation",
    )
    monthly_budget_usd: Mapped[float | None] = mapped_column(
        Float, comment="Monthly email spending limit in USD",
    )

    # Provider-specific configuration (JSON blob)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="Additional provider-specific configuration",
    )

    # Encryption versioning (for key rotation)
    encryption_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="Encryption key version for rotation",
    )

    # Relationships (id, timestamps, audit FKs provided by base classes)
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="email_configs")
    created_by: Mapped[User | None] = relationship("User", foreign_keys="EmailConfig.created_by_id")
    updated_by: Mapped[User | None] = relationship("User", foreign_keys="EmailConfig.updated_by_id")

    __table_args__ = (
        Index("ix_email_configs_tenant_active", "tenant_id", "is_active"),
        Index("ix_email_configs_provider", "provider_type"),
    )

    def __repr__(self) -> str:
        """Return email config summary for debugging."""
        return (
            f"<EmailConfig(tenant_id={self.tenant_id}, "
            f"provider={self.provider_type}, active={self.is_active})>"
        )

    def get_masked_credentials(self) -> dict[str, str | None]:
        """Get credentials with values masked for logging/display.

        Returns dict with first 4 chars of each credential visible.
        """

        def mask(value: str | None) -> str | None:
            if value is None:
                return None
            if len(value) <= 4:
                return "****"
            return f"{value[:4]}****"

        return {
            "smtp_password": mask(self.smtp_password),
            "aws_access_key": mask(self.aws_access_key),
            "aws_secret_key": mask(self.aws_secret_key),
            "api_key": mask(self.api_key),
        }


class EmailUsageLog(Base):
    """Email usage and cost tracking.

    Records detailed metrics for each email operation:
    - Provider used
    - Recipient count
    - Calculated costs
    - Processing duration
    - Success/failure status

    Used for:
    - Per-tenant cost tracking and billing
    - Usage analytics and reporting
    - Monthly budget enforcement
    - Provider performance comparison

    Examples:
        EmailUsageLog(
            tenant_id="tenant-123",
            provider="sendgrid",
            recipients_count=5,
            cost_usd=0.0005,  # $0.0001 per email
            success=True,
            duration_ms=250,
            message_id="sg-abc123"
        )
    """

    __tablename__ = "email_usage_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provider information
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Provider used (smtp, sendgrid, etc.)",
    )
    recipients_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Number of recipients",
    )

    # Cost tracking
    cost_usd: Mapped[float | None] = mapped_column(
        Float, comment="Calculated cost in USD",
    )

    # Delivery information
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="Whether delivery succeeded",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, comment="Delivery duration in milliseconds",
    )
    message_id: Mapped[str | None] = mapped_column(
        String(255), comment="Provider message ID for tracking",
    )
    error_category: Mapped[str | None] = mapped_column(
        String(50), comment="Error category if failed (auth, network, recipient, quota)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="Error details if failed",
    )

    # Correlation
    trace_id: Mapped[str | None] = mapped_column(
        String(64), comment="OpenTelemetry trace ID for correlation",
    )
    template_name: Mapped[str | None] = mapped_column(
        String(255), comment="Template used (if any)",
    )

    # Additional metadata
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="Additional operation metadata",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant")

    __table_args__ = (
        Index("ix_email_usage_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_email_usage_logs_tenant_provider", "tenant_id", "provider"),
        Index("ix_email_usage_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """Return usage log summary for debugging."""
        return (
            f"<EmailUsageLog(tenant_id={self.tenant_id}, provider={self.provider}, "
            f"success={self.success}, cost=${self.cost_usd or 0:.4f})>"
        )


class EmailAuditLog(Base):
    """Privacy-compliant email audit trail.

    Records audit information for sent emails while protecting PII:
    - Recipient email is hashed (SHA256) for privacy
    - No email content is stored
    - Supports compliance queries ("was email sent to X")

    Examples:
        EmailAuditLog(
            tenant_id="tenant-123",
            recipient_hash=sha256("user@example.com"),
            template_name="welcome",
            status="sent",
            provider="smtp"
        )
    """

    __tablename__ = "email_audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        index=True,
        comment="Tenant ID (nullable for system emails)",
    )

    # Recipient (hashed for privacy)
    recipient_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="SHA256 hash of recipient email",
    )

    # Email metadata (non-PII)
    template_name: Mapped[str | None] = mapped_column(
        String(255), comment="Template used",
    )
    subject_hash: Mapped[str | None] = mapped_column(
        String(64), comment="SHA256 hash of subject (for duplicate detection)",
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Status: queued, sent, failed, bounced",
    )
    provider: Mapped[str | None] = mapped_column(
        String(50), comment="Provider used",
    )
    message_id: Mapped[str | None] = mapped_column(
        String(255), comment="Provider message ID",
    )

    # Error information
    error_category: Mapped[str | None] = mapped_column(
        String(50), comment="Error category if failed",
    )

    # Correlation
    trace_id: Mapped[str | None] = mapped_column(
        String(64), comment="OpenTelemetry trace ID",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False, index=True,
    )

    # Relationships
    tenant: Mapped[Tenant | None] = relationship("Tenant")

    __table_args__ = (
        Index("ix_email_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_email_audit_logs_recipient", "recipient_hash", "created_at"),
        Index("ix_email_audit_logs_status", "status", "created_at"),
    )

    def __repr__(self) -> str:
        """Return audit log summary for debugging."""
        return (
            f"<EmailAuditLog(tenant_id={self.tenant_id}, "
            f"recipient_hash={self.recipient_hash[:8]}..., status={self.status})>"
        )


__all__ = [
    "EmailAuditLog",
    "EmailConfig",
    "EmailProviderType",
    "EmailUsageLog",
]
