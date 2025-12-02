"""Pydantic schemas for the webhooks feature."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from example_service.core.validators import (
    validate_custom_headers_optional,
    validate_event_types,
    validate_event_types_optional,
)


class DeliveryStatus(str, Enum):
    """Webhook delivery status enumeration."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookBase(BaseModel):
    """Shared attributes for webhook payloads."""

    name: str = Field(..., max_length=200, description="Human-readable webhook name")
    description: str | None = Field(None, description="Webhook description")
    url: HttpUrl = Field(..., description="Target URL for webhook delivery")
    event_types: list[str] = Field(
        ..., min_length=1, description="List of event types to subscribe to"
    )
    is_active: bool = Field(default=True, description="Whether webhook is active")
    max_retries: int = Field(default=5, ge=0, le=10, description="Maximum delivery retry attempts")
    timeout_seconds: int = Field(
        default=30, ge=1, le=300, description="HTTP request timeout in seconds"
    )
    custom_headers: dict[str, str] | None = Field(
        None, description="Additional HTTP headers to include in requests"
    )

    @field_validator("event_types")
    @classmethod
    def check_event_types(cls, v: list[str]) -> list[str]:
        """Validate event types are non-empty strings."""
        return validate_event_types(v)

    @field_validator("custom_headers")
    @classmethod
    def check_custom_headers(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Validate custom headers don't override system headers."""
        return validate_custom_headers_optional(v)


class WebhookCreate(WebhookBase):
    """Payload used when creating a webhook."""


class WebhookUpdate(BaseModel):
    """Payload used when updating a webhook."""

    name: str | None = Field(None, max_length=200, description="Human-readable webhook name")
    description: str | None = Field(None, description="Webhook description")
    url: HttpUrl | None = Field(None, description="Target URL for webhook delivery")
    event_types: list[str] | None = Field(
        None, min_length=1, description="List of event types to subscribe to"
    )
    is_active: bool | None = Field(None, description="Whether webhook is active")
    max_retries: int | None = Field(
        None, ge=0, le=10, description="Maximum delivery retry attempts"
    )
    timeout_seconds: int | None = Field(
        None, ge=1, le=300, description="HTTP request timeout in seconds"
    )
    custom_headers: dict[str, str] | None = Field(
        None, description="Additional HTTP headers to include in requests"
    )

    @field_validator("event_types")
    @classmethod
    def check_event_types(cls, v: list[str] | None) -> list[str] | None:
        """Validate event types are non-empty strings."""
        return validate_event_types_optional(v)

    @field_validator("custom_headers")
    @classmethod
    def check_custom_headers(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Validate custom headers don't override system headers."""
        return validate_custom_headers_optional(v)


class WebhookRead(WebhookBase):
    """Representation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    secret: str = Field(..., description="HMAC secret for signing payloads")
    created_at: datetime
    updated_at: datetime


class WebhookList(BaseModel):
    """Paginated list of webhooks."""

    items: list[WebhookRead]
    total: int
    limit: int
    offset: int


class WebhookDeliveryRead(BaseModel):
    """Representation of a webhook delivery attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_id: UUID
    event_type: str
    event_id: str
    payload: dict
    status: DeliveryStatus
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    response_status_code: int | None
    response_body: str | None
    response_time_ms: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class WebhookDeliveryList(BaseModel):
    """Paginated list of webhook deliveries."""

    items: list[WebhookDeliveryRead]
    total: int
    limit: int
    offset: int


class WebhookTestRequest(BaseModel):
    """Request to test a webhook."""

    event_type: str = Field(default="webhook.test", description="Event type for test delivery")
    payload: dict = Field(default_factory=dict, description="Test payload data")


class WebhookTestResponse(BaseModel):
    """Response from testing a webhook."""

    success: bool = Field(..., description="Whether the test delivery succeeded")
    status_code: int | None = Field(None, description="HTTP response status code")
    response_time_ms: int | None = Field(None, description="Response time in milliseconds")
    error_message: str | None = Field(None, description="Error message if test failed")
    delivery_id: UUID | None = Field(None, description="ID of the delivery record created")


class SecretRegenerateResponse(BaseModel):
    """Response from regenerating webhook secret."""

    webhook_id: UUID
    secret: str = Field(..., description="New HMAC secret")
    message: str = Field(default="Secret regenerated successfully")
