"""Mutation resolvers for webhooks.

Provides write operations for webhooks:
- createWebhook: Create a new webhook
- updateWebhook: Update an existing webhook
- deleteWebhook: Delete a webhook
- testWebhook: Test webhook delivery
- retryDelivery: Retry a failed delivery
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError
import strawberry

from example_service.features.graphql.events import (
    publish_webhook_event,
    serialize_model_for_event,
)
from example_service.features.graphql.types.webhooks import (
    CreateWebhookInput,
    DeletePayload,
    TestWebhookInput,
    UpdateWebhookInput,
    WebhookError,
    WebhookErrorCode,
    WebhookPayload,
    WebhookSuccess,
    WebhookTestResult,
    WebhookType,
)
from example_service.features.webhooks.models import Webhook, WebhookDelivery
from example_service.features.webhooks.repository import (
    get_webhook_delivery_repository,
    get_webhook_repository,
)
from example_service.features.webhooks.schemas import WebhookRead

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


def generate_webhook_secret() -> str:
    """Generate a secure random secret for webhook signing."""
    return secrets.token_urlsafe(32)


async def create_webhook_mutation(
    info: Info[GraphQLContext, None],
    input: CreateWebhookInput,
) -> WebhookPayload:
    """Create a new webhook."""
    ctx = info.context

    try:
        create_data = input.to_pydantic()
    except Exception as e:
        return WebhookError(
            code=WebhookErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    try:
        webhook = Webhook(
            name=create_data.name,
            description=create_data.description,
            url=str(create_data.url),
            secret=generate_webhook_secret(),
            event_types=create_data.event_types,
            is_active=create_data.is_active,
            max_retries=create_data.max_retries,
            timeout_seconds=create_data.timeout_seconds,
            custom_headers=create_data.custom_headers,
        )

        ctx.session.add(webhook)
        await ctx.session.commit()
        await ctx.session.refresh(webhook)

        logger.info(f"Created webhook: {webhook.id} ({webhook.name})")

        # Publish event for real-time subscriptions
        await publish_webhook_event(
            event_type="CREATED",
            webhook_data=serialize_model_for_event(webhook),
        )

        webhook_pydantic = WebhookRead.from_orm(webhook)
        return WebhookSuccess(webhook=WebhookType.from_pydantic(webhook_pydantic))

    except IntegrityError as e:
        await ctx.session.rollback()
        logger.exception(f"Error creating webhook: {e}")
        return WebhookError(
            code=WebhookErrorCode.INTERNAL_ERROR,
            message="Failed to create webhook",
        )
    except Exception as e:
        logger.exception(f"Error creating webhook: {e}")
        await ctx.session.rollback()
        return WebhookError(
            code=WebhookErrorCode.INTERNAL_ERROR,
            message="Failed to create webhook",
        )


async def update_webhook_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    input: UpdateWebhookInput,
) -> WebhookPayload:
    """Update an existing webhook."""
    ctx = info.context
    repo = get_webhook_repository()

    try:
        webhook_uuid = UUID(str(id))
    except ValueError:
        return WebhookError(
            code=WebhookErrorCode.VALIDATION_ERROR,
            message="Invalid webhook ID format",
            field="id",
        )

    try:
        update_data = input.to_pydantic()
    except Exception as e:
        return WebhookError(
            code=WebhookErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    try:
        webhook = await repo.get(ctx.session, webhook_uuid)
        if webhook is None:
            return WebhookError(
                code=WebhookErrorCode.NOT_FOUND,
                message=f"Webhook with ID {id} not found",
            )

        update_dict = update_data.model_dump(exclude_unset=True)

        if "name" in update_dict:
            webhook.name = update_dict["name"]
        if "description" in update_dict:
            webhook.description = update_dict["description"]
        if "url" in update_dict:
            webhook.url = str(update_dict["url"])
        if "event_types" in update_dict:
            webhook.event_types = update_dict["event_types"]
        if "is_active" in update_dict:
            webhook.is_active = update_dict["is_active"]
        if "max_retries" in update_dict:
            webhook.max_retries = update_dict["max_retries"]
        if "timeout_seconds" in update_dict:
            webhook.timeout_seconds = update_dict["timeout_seconds"]
        if "custom_headers" in update_dict:
            webhook.custom_headers = update_dict["custom_headers"]

        await ctx.session.commit()
        await ctx.session.refresh(webhook)

        logger.info(f"Updated webhook: {webhook.id} ({webhook.name})")

        # Publish event for real-time subscriptions
        await publish_webhook_event(
            event_type="UPDATED",
            webhook_data=serialize_model_for_event(webhook),
        )

        webhook_pydantic = WebhookRead.from_orm(webhook)
        return WebhookSuccess(webhook=WebhookType.from_pydantic(webhook_pydantic))

    except Exception as e:
        logger.exception(f"Error updating webhook: {e}")
        await ctx.session.rollback()
        return WebhookError(
            code=WebhookErrorCode.INTERNAL_ERROR,
            message="Failed to update webhook",
        )


async def delete_webhook_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> DeletePayload:
    """Delete a webhook."""
    ctx = info.context
    repo = get_webhook_repository()

    try:
        webhook_uuid = UUID(str(id))
    except ValueError:
        return DeletePayload(success=False, message="Invalid webhook ID format")

    try:
        webhook = await repo.get(ctx.session, webhook_uuid)
        if webhook is None:
            return DeletePayload(success=False, message=f"Webhook with ID {id} not found")

        # Capture webhook data before deletion
        webhook_data = serialize_model_for_event(webhook)
        webhook_name = webhook.name

        await repo.delete(ctx.session, webhook)
        await ctx.session.commit()

        logger.info(f"Deleted webhook: {webhook_uuid} ({webhook_name})")

        # Publish event for real-time subscriptions
        await publish_webhook_event(
            event_type="DELETED",
            webhook_data=webhook_data,
        )

        return DeletePayload(success=True, message="Webhook deleted successfully")

    except Exception as e:
        logger.exception(f"Error deleting webhook: {e}")
        await ctx.session.rollback()
        return DeletePayload(success=False, message="Failed to delete webhook")


async def test_webhook_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    input: TestWebhookInput | None = None,  # noqa: PT028
) -> WebhookTestResult:
    """Test a webhook by sending a test delivery."""
    ctx = info.context
    repo = get_webhook_repository()

    try:
        webhook_uuid = UUID(str(id))
    except ValueError:
        return WebhookTestResult(
            success=False,
            error_message="Invalid webhook ID format",
        )

    try:
        webhook = await repo.get(ctx.session, webhook_uuid)
        if webhook is None:
            return WebhookTestResult(
                success=False,
                error_message=f"Webhook with ID {id} not found",
            )

        # For now, create a pending delivery record
        # In a real implementation, this would trigger the delivery task
        test_input = input if input else TestWebhookInput()

        delivery = WebhookDelivery(
            webhook_id=webhook_uuid,
            event_type=test_input.event_type,
            event_id=f"test-{secrets.token_urlsafe(8)}",
            payload=test_input.payload,
            status="pending",
            max_attempts=1,
        )

        ctx.session.add(delivery)
        await ctx.session.commit()
        await ctx.session.refresh(delivery)

        logger.info(f"Test delivery created for webhook: {webhook_uuid}")

        return WebhookTestResult(
            success=True,
            delivery_id=strawberry.ID(str(delivery.id)),
        )

    except Exception as e:
        logger.exception(f"Error testing webhook: {e}")
        await ctx.session.rollback()
        return WebhookTestResult(
            success=False,
            error_message=f"Failed to test webhook: {e!s}",
        )


async def retry_delivery_mutation(
    info: Info[GraphQLContext, None],
    delivery_id: strawberry.ID,
) -> DeletePayload:
    """Retry a failed webhook delivery."""
    ctx = info.context
    repo = get_webhook_delivery_repository()

    try:
        delivery_uuid = UUID(str(delivery_id))
    except ValueError:
        return DeletePayload(success=False, message="Invalid delivery ID format")

    try:
        delivery = await repo.get(ctx.session, delivery_uuid)
        if delivery is None:
            return DeletePayload(success=False, message=f"Delivery with ID {delivery_id} not found")

        if delivery.status == "delivered":
            return DeletePayload(success=False, message="Delivery already succeeded")

        if delivery.attempt_count >= delivery.max_attempts:
            return DeletePayload(success=False, message="Delivery has exhausted all retries")

        # Reset for retry
        delivery.status = "pending"
        delivery.next_retry_at = None

        await ctx.session.commit()

        logger.info(f"Retry scheduled for delivery: {delivery_uuid}")

        return DeletePayload(success=True, message="Delivery retry scheduled")

    except Exception as e:
        logger.exception(f"Error retrying delivery: {e}")
        await ctx.session.rollback()
        return DeletePayload(success=False, message="Failed to retry delivery")


__all__ = [
    "create_webhook_mutation",
    "delete_webhook_mutation",
    "retry_delivery_mutation",
    "test_webhook_mutation",
    "update_webhook_mutation",
]
