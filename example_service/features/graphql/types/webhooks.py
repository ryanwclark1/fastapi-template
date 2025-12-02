"""GraphQL types for webhooks feature.

Provides Strawberry GraphQL types for webhook management with full Pydantic integration.
Webhooks enable external systems to receive HTTP POST notifications for subscribed events.

Auto-generated from Pydantic schemas:
- WebhookType: Auto-generated from WebhookRead
- WebhookDeliveryType: Auto-generated from WebhookDeliveryRead
- CreateWebhookInput: Auto-generated from WebhookCreate
- UpdateWebhookInput: Auto-generated from WebhookUpdate
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import strawberry

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_field,
    pydantic_input,
    pydantic_type,
)
from example_service.features.webhooks.schemas import (
    DeliveryStatus as PydanticDeliveryStatus,
)
from example_service.features.webhooks.schemas import (
    WebhookCreate,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookUpdate,
)

if TYPE_CHECKING:
    from strawberry.types import Info

# ============================================================================
# Enums
# ============================================================================


@strawberry.enum(description="Webhook delivery status")
class DeliveryStatus:
    """Webhook delivery status types."""

    PENDING = "pending"  # Waiting for delivery
    DELIVERED = "delivered"  # Successfully delivered
    FAILED = "failed"  # Delivery failed after all retries
    RETRYING = "retrying"  # Retrying after failure


# ============================================================================
# Webhook Delivery Type (Output)
# ============================================================================


@pydantic_type(model=WebhookDeliveryRead, description="A webhook delivery attempt")
class WebhookDeliveryType:
    """Webhook delivery type auto-generated from WebhookDeliveryRead Pydantic schema.

    Tracks individual webhook delivery attempts including:
    - HTTP response codes and timing
    - Retry attempts and scheduling
    - Error messages for failed deliveries

    All fields are auto-generated from the Pydantic WebhookDeliveryRead schema.
    """

    # Override ID fields
    id: strawberry.ID = pydantic_field(description="Unique identifier for the delivery")
    webhook_id: strawberry.ID = pydantic_field(description="Parent webhook ID")

    # Computed fields
    @strawberry.field(description="Whether this delivery succeeded")
    def is_successful(self) -> bool:
        """Check if delivery was successful.

        Returns:
            True if status is DELIVERED
        """
        if hasattr(self, "status"):
            return self.status == PydanticDeliveryStatus.DELIVERED.value
        return False

    @strawberry.field(description="Whether this delivery has exhausted retries")
    def is_exhausted(self) -> bool:
        """Check if delivery has exhausted all retry attempts.

        Returns:
            True if attempt_count >= max_attempts
        """
        if hasattr(self, "attempt_count") and hasattr(self, "max_attempts"):
            return self.attempt_count >= self.max_attempts
        return False


# ============================================================================
# Webhook Type (Output)
# ============================================================================


@pydantic_type(model=WebhookRead, description="A webhook endpoint configuration")
class WebhookType:
    """Webhook type auto-generated from WebhookRead Pydantic schema.

    Webhooks provide:
    - Event subscriptions (specific event types)
    - HTTP POST delivery to configured URLs
    - HMAC signature authentication
    - Automatic retry with exponential backoff
    - Custom headers support

    All fields are auto-generated from the Pydantic WebhookRead schema.
    """

    # Override ID field
    id: strawberry.ID = pydantic_field(description="Unique identifier for the webhook")

    # Override event_types as GraphQL expects list[str]
    @strawberry.field(description="List of event types this webhook subscribes to")
    def event_types(self) -> list[str]:
        """Get event types with proper type conversion.

        Returns:
            List of event type strings
        """
        if hasattr(self, "_event_types") and self._event_types:
            return list(self._event_types)
        return []

    # Computed fields
    @strawberry.field(description="Recent deliveries for this webhook")
    async def recent_deliveries(
        self,
        info: Info,
        limit: int = 10,
    ) -> list[WebhookDeliveryType]:
        """Get recent delivery attempts for this webhook.

        Uses DataLoader for efficient batching.

        Args:
            info: Strawberry info with context
            limit: Maximum number of deliveries to return

        Returns:
            List of recent webhook deliveries
        """
        from uuid import UUID

        from example_service.features.webhooks.schemas import WebhookDeliveryRead

        # Get webhook_id
        webhook_id = UUID(str(self.id))

        # Use DataLoader to get deliveries
        deliveries = await info.context.loaders.webhook_deliveries_by_webhook.load(webhook_id)

        # Limit results
        limited_deliveries = list(deliveries)[:limit]

        return [
            WebhookDeliveryType.from_pydantic(WebhookDeliveryRead.from_orm(d))
            for d in limited_deliveries
        ]


# ============================================================================
# Input Types
# ============================================================================


@pydantic_input(
    model=WebhookCreate,
    fields=[
        "name",
        "description",
        "url",
        "event_types",
        "is_active",
        "max_retries",
        "timeout_seconds",
        "custom_headers",
    ],
    description="Input for creating a webhook",
)
class CreateWebhookInput:
    """Input for creating a webhook.

    Auto-generated from WebhookCreate Pydantic schema.
    Pydantic validators run automatically:
    - name: max 200 characters
    - url: valid HTTP/HTTPS URL
    - event_types: non-empty, valid event type strings
    - max_retries: 0-10
    - timeout_seconds: 1-300
    """


@pydantic_input(
    model=WebhookUpdate,
    fields=[
        "name",
        "description",
        "url",
        "event_types",
        "is_active",
        "max_retries",
        "timeout_seconds",
        "custom_headers",
    ],
    description="Input for updating a webhook",
)
class UpdateWebhookInput:
    """Input for updating a webhook.

    All fields are optional - only provided fields are updated.
    Auto-generated from WebhookUpdate Pydantic schema.
    """


@strawberry.input(description="Input for testing a webhook")
class TestWebhookInput:
    """Input for testing a webhook delivery."""

    event_type: str = strawberry.field(
        default="webhook.test",
        description="Event type for test delivery",
    )
    payload: strawberry.scalars.JSON = strawberry.field(
        default_factory=dict,
        description="Test payload data",
    )


# ============================================================================
# Response Types
# ============================================================================


@strawberry.type(description="Webhook test result")
class WebhookTestResult:
    """Result from testing a webhook."""

    success: bool = strawberry.field(description="Whether the test delivery succeeded")
    status_code: int | None = strawberry.field(
        default=None,
        description="HTTP response status code",
    )
    response_time_ms: int | None = strawberry.field(
        default=None,
        description="Response time in milliseconds",
    )
    error_message: str | None = strawberry.field(
        default=None,
        description="Error message if test failed",
    )
    delivery_id: strawberry.ID | None = strawberry.field(
        default=None,
        description="ID of the delivery record created",
    )


@strawberry.type(description="Webhook operation success response")
class WebhookSuccess:
    """Successful webhook operation response."""

    webhook: WebhookType


@strawberry.enum(description="Webhook error codes")
class WebhookErrorCode(strawberry.enum.EnumMeta):
    """Error codes for webhook operations."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_URL = "DUPLICATE_URL"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@strawberry.type(description="Webhook operation error")
class WebhookError:
    """Error response for webhook operations."""

    code: WebhookErrorCode
    message: str
    field: str | None = None


# Union type for mutations
WebhookPayload = strawberry.union("WebhookPayload", (WebhookSuccess, WebhookError))


@strawberry.type(description="Generic success/failure response")
class DeletePayload:
    """Response for delete operations."""

    success: bool
    message: str


# ============================================================================
# Edge and Connection Types for Pagination
# ============================================================================


@strawberry.type(description="Edge containing a webhook node and cursor")
class WebhookEdge:
    """Edge in a Relay-style connection."""

    node: WebhookType
    cursor: str


@strawberry.type(description="Paginated list of webhooks")
class WebhookConnection:
    """Relay-style connection for webhook pagination."""

    edges: list[WebhookEdge]
    page_info: PageInfoType


@strawberry.type(description="Edge containing a delivery node and cursor")
class WebhookDeliveryEdge:
    """Edge in a Relay-style connection."""

    node: WebhookDeliveryType
    cursor: str


@strawberry.type(description="Paginated list of webhook deliveries")
class WebhookDeliveryConnection:
    """Relay-style connection for webhook delivery pagination."""

    edges: list[WebhookDeliveryEdge]
    page_info: PageInfoType


# ============================================================================
# Subscription Event Types
# ============================================================================


@strawberry.enum(description="Types of webhook delivery events for subscriptions")
class WebhookDeliveryEventType(strawberry.enum.Enum):
    """Event types for webhook delivery subscriptions.

    Clients can subscribe to specific event types or all events.
    """

    DELIVERED = "DELIVERED"  # Successfully delivered
    FAILED = "FAILED"  # Delivery failed (exhausted retries)
    RETRYING = "RETRYING"  # Retrying after failure


@strawberry.type(description="Real-time webhook delivery event via subscription")
class WebhookDeliveryEvent:
    """Event payload for webhook delivery subscriptions.

    Pushed to subscribed clients when webhook deliveries are attempted.
    Useful for monitoring webhook health and debugging delivery issues.
    """

    event_type: WebhookDeliveryEventType = strawberry.field(
        description="Type of event that occurred"
    )
    delivery: WebhookDeliveryType = strawberry.field(description="Delivery attempt data")
    webhook_id: strawberry.ID = strawberry.field(description="Parent webhook ID")


__all__ = [
    # Inputs
    "CreateWebhookInput",
    "DeletePayload",
    # Enums
    "DeliveryStatus",
    "TestWebhookInput",
    "UpdateWebhookInput",
    "WebhookConnection",
    "WebhookDeliveryConnection",
    "WebhookDeliveryEdge",
    "WebhookDeliveryEvent",
    "WebhookDeliveryEventType",
    "WebhookDeliveryType",
    # Pagination
    "WebhookEdge",
    "WebhookError",
    "WebhookErrorCode",
    "WebhookPayload",
    # Responses
    "WebhookSuccess",
    "WebhookTestResult",
    # Types
    "WebhookType",
]
