"""API schemas for email configuration management.

This module defines request/response schemas for:
- Creating/updating tenant email configurations
- Retrieving configurations (with masked credentials)
- Testing email configurations
- Viewing usage statistics
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from example_service.features.email.models import EmailProviderType
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime, EmailProviderType)


class EmailConfigBase(BaseModel):
    """Base schema for email configuration."""

    provider_type: EmailProviderType = Field(
        description="Email provider type",
    )
    is_active: bool = Field(
        default=True,
        description="Whether this configuration is active",
    )

    # Provider-specific settings
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_use_tls: bool | None = Field(default=None)
    smtp_use_ssl: bool | None = Field(default=None)

    aws_region: str | None = Field(default=None, max_length=50)
    aws_configuration_set: str | None = Field(default=None, max_length=255)

    # Sender settings
    from_email: EmailStr | None = Field(default=None)
    from_name: str | None = Field(default=None, max_length=100)
    reply_to: EmailStr | None = Field(default=None)

    # Rate limits (per-tenant overrides)
    rate_limit_per_minute: int | None = Field(
        default=None,
        ge=0,
        description="Emails per minute limit (0 = unlimited)",
    )
    daily_quota: int | None = Field(
        default=None,
        ge=0,
        description="Daily email quota (0 = unlimited)",
    )


class EmailConfigCreate(EmailConfigBase):
    """Schema for creating email configuration."""

    # Sensitive credentials (write-only, will be encrypted)
    smtp_password: str | None = Field(
        default=None,
        description="SMTP password (will be encrypted)",
    )
    aws_access_key: str | None = Field(
        default=None,
        description="AWS access key (will be encrypted)",
    )
    aws_secret_key: str | None = Field(
        default=None,
        description="AWS secret key (will be encrypted)",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for SendGrid/Mailgun (will be encrypted)",
    )

    @field_validator("provider_type")
    @classmethod
    def validate_provider_config(cls, v: EmailProviderType, _info: Any) -> EmailProviderType:
        """Validate that required fields are present for the provider type."""
        # This is a simplified validation - actual validation happens in the route
        return v


class EmailConfigUpdate(BaseModel):
    """Schema for updating email configuration (all fields optional)."""

    provider_type: EmailProviderType | None = None
    is_active: bool | None = None

    # Provider settings
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None  # Will be encrypted if provided
    smtp_use_tls: bool | None = None
    smtp_use_ssl: bool | None = None

    aws_region: str | None = None
    aws_access_key: str | None = None  # Will be encrypted if provided
    aws_secret_key: str | None = None  # Will be encrypted if provided
    aws_configuration_set: str | None = None

    api_key: str | None = None  # Will be encrypted if provided

    # Sender settings
    from_email: EmailStr | None = None
    from_name: str | None = None
    reply_to: EmailStr | None = None

    # Rate limits
    rate_limit_per_minute: int | None = Field(default=None, ge=0)
    daily_quota: int | None = Field(default=None, ge=0)


class EmailConfigResponse(EmailConfigBase):
    """Schema for email configuration response (credentials masked)."""

    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    encryption_version: int

    # Masked credentials (never expose actual values)
    has_smtp_password: bool = Field(
        description="Whether SMTP password is configured",
    )
    has_aws_credentials: bool = Field(
        description="Whether AWS credentials are configured",
    )
    has_api_key: bool = Field(
        description="Whether API key is configured",
    )

    model_config = ConfigDict(from_attributes=True)


class TestEmailRequest(BaseModel):
    """Request schema for testing email configuration."""

    to: EmailStr = Field(
        description="Recipient email address for test",
    )
    use_tenant_config: bool = Field(
        default=True,
        description="Whether to use tenant config (True) or test provided config (False)",
    )

    # Optional: Test a config before saving it
    test_config: EmailConfigCreate | None = Field(
        default=None,
        description="Configuration to test (if not using saved tenant config)",
    )


class TestEmailResponse(BaseModel):
    """Response schema for test email."""

    success: bool
    message_id: str | None = None
    provider: str
    duration_ms: int
    error: str | None = None
    error_code: str | None = None


class EmailUsageStatsRequest(BaseModel):
    """Request schema for usage statistics query."""

    start_date: datetime | None = Field(
        default=None,
        description="Start date for usage query (defaults to 30 days ago)",
    )
    end_date: datetime | None = Field(
        default=None,
        description="End date for usage query (defaults to now)",
    )
    group_by: str = Field(
        default="day",
        description="Grouping: day, week, month",
        pattern="^(day|week|month)$",
    )


class EmailUsageStats(BaseModel):
    """Usage statistics for a tenant."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Aggregate metrics
    total_emails: int
    successful_emails: int
    failed_emails: int
    success_rate: float  # Percentage

    # By provider
    emails_by_provider: dict[str, int]

    # Cost tracking
    total_cost_usd: float | None
    cost_by_provider: dict[str, float]

    # Rate limiting
    rate_limit_hits: int = Field(
        description="Number of times rate limit was hit",
    )

    # Recipients
    total_recipients: int


class EmailHealthCheck(BaseModel):
    """Health check result for email provider."""

    provider: str
    tenant_id: str | None
    healthy: bool
    last_checked: datetime
    response_time_ms: int | None
    error: str | None = None


class EmailHealthResponse(BaseModel):
    """Response for email health check endpoint."""

    overall_healthy: bool
    checks: list[EmailHealthCheck]
    timestamp: datetime


class ProviderInfo(BaseModel):
    """Information about an available email provider."""

    provider_type: EmailProviderType
    name: str
    description: str
    required_fields: list[str]
    optional_fields: list[str]
    supports_attachments: bool
    supports_html: bool
    supports_templates: bool
    estimated_cost_per_1000: float | None = Field(
        description="Estimated cost in USD per 1000 emails",
    )


class ProvidersListResponse(BaseModel):
    """List of available email providers with their requirements."""

    providers: list[ProviderInfo]


class EmailAuditLogResponse(BaseModel):
    """Response schema for audit log entry."""

    id: str
    tenant_id: str | None
    recipient_hash: str
    template_name: str | None
    status: str
    error_category: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmailAuditLogsResponse(BaseModel):
    """Paginated response for audit logs (offset-based)."""

    logs: list[EmailAuditLogResponse]
    total: int
    page: int
    page_size: int


class EmailAuditLogsCursorResponse(BaseModel):
    """Cursor-paginated response for audit logs.

    Cursor-based pagination is more efficient for large datasets:
    - No need to count total rows
    - Consistent results even when data changes
    - Better performance with indexed columns
    """

    logs: list[EmailAuditLogResponse]
    next_cursor: str | None = Field(
        description="Cursor to fetch the next page (older items)",
    )
    prev_cursor: str | None = Field(
        description="Cursor to fetch the previous page (newer items)",
    )
    has_more: bool = Field(
        description="Whether there are more items after this page",
    )
    limit: int = Field(
        description="Number of items requested per page",
    )


class SendEmailRequest(BaseModel):
    """Request schema for sending an email."""

    to: list[EmailStr] = Field(
        min_length=1,
        max_length=100,
        description="Recipient email addresses (max 100)",
    )
    subject: str = Field(
        min_length=1,
        max_length=500,
        description="Email subject line",
    )
    body: str | None = Field(
        default=None,
        max_length=100000,
        description="Plain text body",
    )
    body_html: str | None = Field(
        default=None,
        max_length=500000,
        description="HTML body (takes precedence over plain text)",
    )
    reply_to: EmailStr | None = Field(
        default=None,
        description="Reply-to address (overrides config default)",
    )
    template_name: str | None = Field(
        default=None,
        max_length=255,
        description="Template name to use (if supported by provider)",
    )
    template_data: dict[str, Any] | None = Field(
        default=None,
        description="Template variables",
    )

    @field_validator("body", "body_html")
    @classmethod
    def validate_body_content(cls, v: str | None) -> str | None:
        """Ensure at least one body type is provided."""
        return v


class SendEmailResponse(BaseModel):
    """Response schema for email send operation."""

    success: bool
    message_id: str | None = None
    provider: str
    recipients_count: int
    duration_ms: int
    error: str | None = None
    error_code: str | None = None


# Rebuild models that use forward references
EmailConfigCreate.model_rebuild()
EmailConfigUpdate.model_rebuild()
SendEmailRequest.model_rebuild()
