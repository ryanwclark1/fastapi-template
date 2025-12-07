"""Email schemas and data models.

Defines the structure for email messages, attachments, and delivery results.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class EmailPriority(StrEnum):
    """Email priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class EmailStatus(StrEnum):
    """Email delivery status."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"
    DELIVERED = "delivered"


class EmailAttachment(BaseModel):
    """Email attachment model.

    Supports both inline content and file paths.

    Example:
        # From file
        attachment = EmailAttachment(
            filename="report.pdf",
            path="/tmp/report.pdf",
            content_type="application/pdf",
        )

        # From bytes
        attachment = EmailAttachment(
            filename="data.csv",
            content=b"col1,col2\\n1,2\\n",
            content_type="text/csv",
        )
    """

    filename: str = Field(
        min_length=1,
        max_length=255,
        description="Attachment filename",
    )
    content: bytes | None = Field(
        default=None,
        description="Attachment content as bytes",
    )
    path: str | None = Field(
        default=None,
        description="Path to file to attach",
    )
    content_type: str = Field(
        default="application/octet-stream",
        description="MIME content type",
    )
    content_id: str | None = Field(
        default=None,
        description="Content-ID for inline attachments (e.g., images in HTML)",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate that either content or path is provided."""
        if self.content is None and self.path is None:
            msg = "Either content or path must be provided"
            raise ValueError(msg)


class EmailMessage(BaseModel):
    """Email message model.

    Represents a complete email message ready for sending.

    Example:
        message = EmailMessage(
            to=["user@example.com"],
            subject="Welcome!",
            body_text="Welcome to our service.",
            body_html="<h1>Welcome!</h1><p>Welcome to our service.</p>",
        )
    """

    # Recipients
    to: list[EmailStr] = Field(
        min_length=1,
        description="Primary recipients",
    )
    cc: list[EmailStr] = Field(
        default_factory=list,
        description="CC recipients",
    )
    bcc: list[EmailStr] = Field(
        default_factory=list,
        description="BCC recipients",
    )
    reply_to: EmailStr | None = Field(
        default=None,
        description="Reply-to address",
    )

    # Sender (optional, uses default if not provided)
    from_email: EmailStr | None = Field(
        default=None,
        description="Sender email address",
    )
    from_name: str | None = Field(
        default=None,
        max_length=100,
        description="Sender display name",
    )

    # Content
    subject: str = Field(
        min_length=1,
        max_length=500,
        description="Email subject line",
    )
    body_text: str | None = Field(
        default=None,
        description="Plain text body",
    )
    body_html: str | None = Field(
        default=None,
        description="HTML body",
    )

    # Attachments
    attachments: list[EmailAttachment] = Field(
        default_factory=list,
        description="File attachments",
    )

    # Metadata
    priority: EmailPriority = Field(
        default=EmailPriority.NORMAL,
        description="Email priority",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional email headers",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for tracking/filtering",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom metadata for tracking",
    )

    # Template info (populated when using templates)
    template_name: str | None = Field(
        default=None,
        description="Template name used to generate this email",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate that at least one body type is provided."""
        if self.body_text is None and self.body_html is None:
            msg = "Either body_text or body_html must be provided"
            raise ValueError(msg)

    @property
    def all_recipients(self) -> list[str]:
        """Get all recipients (to, cc, bcc)."""
        return list(self.to) + list(self.cc) + list(self.bcc)

    @property
    def recipient_count(self) -> int:
        """Get total number of recipients."""
        return len(self.all_recipients)


class EmailResult(BaseModel):
    """Result of an email send operation.

    Example:
        result = await email_service.send(message)
        if result.success:
            print(f"Email sent: {result.message_id}")
        else:
            print(f"Failed: {result.error}")
    """

    success: bool = Field(
        description="Whether the email was sent successfully",
    )
    message_id: str | None = Field(
        default=None,
        description="Message ID from the mail server",
    )
    status: EmailStatus = Field(
        default=EmailStatus.PENDING,
        description="Delivery status",
    )
    error: str | None = Field(
        default=None,
        description="Error message if failed",
    )
    error_code: str | None = Field(
        default=None,
        description="Error code for programmatic handling",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the operation completed",
    )
    recipients_accepted: list[str] = Field(
        default_factory=list,
        description="Recipients accepted by the server",
    )
    recipients_rejected: list[str] = Field(
        default_factory=list,
        description="Recipients rejected by the server",
    )
    retry_count: int = Field(
        default=0,
        description="Number of retry attempts made",
    )
    backend: str = Field(
        default="smtp",
        description="Backend used for sending",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (provider info, timing, tenant context)",
    )

    @classmethod
    def success_result(
        cls,
        message_id: str | None = None,
        recipients: list[str] | None = None,
        backend: str = "smtp",
    ) -> EmailResult:
        """Create a success result."""
        return cls(
            success=True,
            message_id=message_id,
            status=EmailStatus.SENT,
            recipients_accepted=recipients or [],
            backend=backend,
        )

    @classmethod
    def failure_result(
        cls,
        error: str,
        error_code: str | None = None,
        retry_count: int = 0,
        backend: str = "smtp",
    ) -> EmailResult:
        """Create a failure result."""
        return cls(
            success=False,
            status=EmailStatus.FAILED,
            error=error,
            error_code=error_code,
            retry_count=retry_count,
            backend=backend,
        )


class EmailTemplateContext(BaseModel):
    """Context for email template rendering.

    Example:
        context = EmailTemplateContext(
            user_name="John Doe",
            action_url="https://example.com/verify",
            custom_data={"order_id": "12345"},
        )
    """

    # Common context variables
    user_name: str | None = Field(default=None, description="Recipient's name")
    user_email: str | None = Field(default=None, description="Recipient's email")
    action_url: str | None = Field(default=None, description="Primary action URL")
    action_text: str | None = Field(default=None, description="Primary action button text")

    # Service info (auto-populated from settings)
    service_name: str | None = Field(default=None, description="Service name")
    service_url: str | None = Field(default=None, description="Service base URL")
    support_email: str | None = Field(default=None, description="Support email address")

    # Custom data
    custom: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional custom context variables",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for template rendering."""
        result = self.model_dump(exclude={"custom"}, exclude_none=True)
        result.update(self.custom)
        return result
