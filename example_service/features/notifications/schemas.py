"""Pydantic schemas for the notifications feature."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime, UUID)


# ============================================================================
# NotificationTemplate Schemas
# ============================================================================


class NotificationTemplateBase(BaseModel):
    """Shared attributes for notification template payloads."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Template identifier (e.g., 'reminder_due')",
    )
    notification_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Category of notification (e.g., 'reminder', 'file')",
    )
    channel: str = Field(
        ...,
        pattern=r"^(email|webhook|websocket|in_app)$",
        description="Delivery channel: email, webhook, websocket, in_app",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Human-readable template description",
    )
    priority: str = Field(
        default="normal",
        pattern=r"^(low|normal|high|urgent)$",
        description="Default priority level",
    )
    is_active: bool = Field(
        default=True,
        description="Whether template is active",
    )


class NotificationTemplateCreate(NotificationTemplateBase):
    """Payload for creating a notification template."""

    # Email templates
    subject_template: str | None = Field(
        default=None,
        description="Jinja2 template for email subject",
    )
    body_template: str | None = Field(
        default=None,
        description="Jinja2 template for plain text email body",
    )
    body_html_template: str | None = Field(
        default=None,
        description="Jinja2 template for HTML email body",
    )

    # Webhook templates
    webhook_payload_template: dict[str, Any] | None = Field(
        default=None,
        description="Jinja2 template structure for webhook payload",
    )

    # WebSocket templates
    websocket_event_type: str | None = Field(
        default=None,
        description="WebSocket event type for client routing",
    )
    websocket_payload_template: dict[str, Any] | None = Field(
        default=None,
        description="Jinja2 template structure for WebSocket payload",
    )

    # Validation
    required_context_vars: list[str] = Field(
        default_factory=list,
        description="Required context variables for rendering",
    )


class NotificationTemplateUpdate(BaseModel):
    """Payload for updating a notification template."""

    description: str | None = None
    is_active: bool | None = None
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|urgent)$",
    )
    subject_template: str | None = None
    body_template: str | None = None
    body_html_template: str | None = None
    webhook_payload_template: dict[str, Any] | None = None
    websocket_event_type: str | None = None
    websocket_payload_template: dict[str, Any] | None = None
    required_context_vars: list[str] | None = None


class NotificationTemplateResponse(NotificationTemplateBase):
    """Representation of a notification template returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str | None
    version: int
    subject_template: str | None = None
    body_template: str | None = None
    body_html_template: str | None = None
    webhook_payload_template: dict[str, Any] | None = None
    websocket_event_type: str | None = None
    websocket_payload_template: dict[str, Any] | None = None
    required_context_vars: list[str]
    created_at: datetime
    updated_at: datetime


class NotificationTemplateListResponse(BaseModel):
    """Response containing a list of notification templates."""

    templates: list[NotificationTemplateResponse]
    total: int


# ============================================================================
# UserNotificationPreference Schemas
# ============================================================================


class UserNotificationPreferenceBase(BaseModel):
    """Shared attributes for user notification preference payloads."""

    notification_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type of notification these preferences apply to",
    )
    enabled_channels: list[str] = Field(
        default_factory=lambda: ["email", "websocket"],
        description="Enabled delivery channels",
    )
    is_active: bool = Field(
        default=True,
        description="Whether these preferences are active",
    )

    @field_validator("enabled_channels")
    @classmethod
    def validate_channels(cls, v: list[str]) -> list[str]:
        """Validate that all channels are supported."""
        valid_channels = {"email", "webhook", "websocket", "in_app"}
        for channel in v:
            if channel not in valid_channels:
                msg = f"Invalid channel: {channel}. Must be one of {valid_channels}"
                raise ValueError(msg)
        return v


class UserNotificationPreferenceCreate(UserNotificationPreferenceBase):
    """Payload for creating user notification preferences."""

    channel_settings: dict[str, Any] | None = Field(
        default=None,
        description="Channel-specific configuration",
    )
    quiet_hours_start: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="Quiet hours start (0-23, UTC)",
    )
    quiet_hours_end: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="Quiet hours end (0-23, UTC)",
    )


class UserNotificationPreferenceUpdate(BaseModel):
    """Payload for updating user notification preferences."""

    enabled_channels: list[str] | None = None
    channel_settings: dict[str, Any] | None = None
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    is_active: bool | None = None

    @field_validator("enabled_channels")
    @classmethod
    def validate_channels(cls, v: list[str] | None) -> list[str] | None:
        """Validate channels if provided."""
        if v is None:
            return v
        valid_channels = {"email", "webhook", "websocket", "in_app"}
        for channel in v:
            if channel not in valid_channels:
                msg = f"Invalid channel: {channel}"
                raise ValueError(msg)
        return v


class UserNotificationPreferenceResponse(UserNotificationPreferenceBase):
    """Representation of user notification preferences returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    tenant_id: str | None
    channel_settings: dict[str, Any] | None = None
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    created_at: datetime
    updated_at: datetime


class UserNotificationPreferenceListResponse(BaseModel):
    """Response containing a list of user notification preferences."""

    preferences: list[UserNotificationPreferenceResponse]
    total: int


# ============================================================================
# Notification Schemas
# ============================================================================


class NotificationBase(BaseModel):
    """Shared attributes for notification payloads."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Notification title",
    )
    body: str | None = Field(
        default=None,
        description="Plain text body",
    )
    body_html: str | None = Field(
        default=None,
        description="HTML body",
    )
    priority: str = Field(
        default="normal",
        pattern=r"^(low|normal|high|urgent)$",
        description="Priority level",
    )


class NotificationCreate(NotificationBase):
    """Payload for creating a notification."""

    notification_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type/category of notification",
    )
    template_name: str | None = Field(
        default=None,
        description="Template to use for rendering (optional)",
    )
    context_data: dict[str, Any] | None = Field(
        default=None,
        description="Template context variables",
    )
    scheduled_for: datetime | None = Field(
        default=None,
        description="When to send notification (null = immediate)",
    )
    source_entity_type: str | None = Field(
        default=None,
        description="Type of entity that triggered notification",
    )
    source_entity_id: str | None = Field(
        default=None,
        description="ID of entity that triggered notification",
    )
    actions: list[dict[str, Any]] | None = Field(
        default=None,
        description="Action buttons for UI",
    )
    progress: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Progress percentage (0-100)",
    )
    group_key: str | None = Field(
        default=None,
        description="Key for grouping related notifications",
    )
    auto_dismiss: bool = Field(
        default=False,
        description="Whether notification auto-dismisses",
    )
    dismiss_after: int | None = Field(
        default=None,
        ge=0,
        description="Auto-dismiss timeout in milliseconds",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="When notification expires",
    )


class NotificationUpdate(BaseModel):
    """Payload for updating a notification."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = None
    body_html: str | None = None
    priority: str | None = Field(default=None, pattern=r"^(low|normal|high|urgent)$")
    read: bool | None = Field(default=None, description="Mark as read/unread")
    status: str | None = Field(
        default=None,
        pattern=r"^(pending|dispatched|delivered|failed|cancelled)$",
    )


class NotificationResponse(NotificationBase):
    """Representation of a notification returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    tenant_id: str | None
    notification_type: str
    template_name: str | None
    context_data: dict[str, Any] | None
    status: str
    scheduled_for: datetime | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    source_event_id: str | None
    source_entity_type: str | None
    source_entity_id: str | None
    correlation_id: str | None
    extra_metadata: dict[str, Any] | None
    actions: list[dict[str, Any]] | None
    progress: int | None
    group_key: str | None
    auto_dismiss: bool
    dismiss_after: int | None
    read: bool
    read_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationWithDeliveriesResponse(NotificationResponse):
    """Notification response including delivery details."""

    deliveries: list[NotificationDeliveryResponse]


class NotificationListResponse(BaseModel):
    """Response containing a list of notifications."""

    notifications: list[NotificationResponse]
    total: int
    unread_count: int


# ============================================================================
# NotificationDelivery Schemas
# ============================================================================


class NotificationDeliveryResponse(BaseModel):
    """Representation of a notification delivery returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    notification_id: UUID
    channel: str
    status: str
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    email_message_id: str | None
    email_recipient: str | None
    webhook_id: UUID | None
    webhook_url: str | None
    websocket_channel: str | None
    websocket_connection_count: int | None
    response_status_code: int | None
    response_body: str | None
    response_time_ms: int | None
    error_message: str | None
    error_category: str | None
    delivered_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationDeliveryListResponse(BaseModel):
    """Response containing a list of notification deliveries."""

    deliveries: list[NotificationDeliveryResponse]
    total: int


# ============================================================================
# Helper Schemas
# ============================================================================


class NotificationStats(BaseModel):
    """Statistics about notification deliveries."""

    total_notifications: int
    total_deliveries: int
    deliveries_by_channel: dict[str, int]
    deliveries_by_status: dict[str, int]
    average_response_time_ms: float | None
    failed_deliveries_count: int


class TemplateRenderRequest(BaseModel):
    """Request to render a template with context."""

    context: dict[str, Any] = Field(
        ...,
        description="Context variables for template rendering",
    )


class TemplateRenderResponse(BaseModel):
    """Response from template rendering."""

    rendered_subject: str | None = None
    rendered_body: str | None = None
    rendered_body_html: str | None = None
    rendered_payload: dict[str, Any] | None = None
