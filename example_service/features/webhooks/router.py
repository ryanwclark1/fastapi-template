"""API router for the webhooks feature."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_db_session
from example_service.features.webhooks.client import WebhookClient
from example_service.features.webhooks.models import WebhookDelivery
from example_service.features.webhooks.schemas import (
    SecretRegenerateResponse,
    WebhookCreate,
    WebhookDeliveryList,
    WebhookDeliveryRead,
    WebhookList,
    WebhookRead,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdate,
)
from example_service.features.webhooks.service import WebhookService
from example_service.infra.logging import get_lazy_logger
from example_service.infra.metrics.tracking import track_feature_usage, track_user_action

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Standard logger for INFO/WARNING/ERROR
logger = logging.getLogger(__name__)
# Lazy logger for DEBUG (zero overhead when DEBUG disabled)
lazy_logger = get_lazy_logger(__name__)


@router.post(
    "/",
    response_model=WebhookRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook",
    description="Create a new webhook endpoint subscription.",
)
async def create_webhook(
    payload: WebhookCreate,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookRead:
    """Create a new webhook.

    Args:
        payload: Webhook creation payload
        session: Database session

    Returns:
        Created webhook with generated secret

    Raises:
        HTTPException: If URL validation fails
    """
    # Track business metrics
    track_feature_usage("webhooks", is_authenticated=False)
    track_user_action("create", is_authenticated=False)

    service = WebhookService(session)

    try:
        webhook = await service.create_webhook(payload)
        await session.commit()
        return WebhookRead.model_validate(webhook)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/",
    response_model=WebhookList,
    summary="List webhooks",
    description="List all webhooks with optional filtering and pagination.",
)
async def list_webhooks(
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookList:
    """List webhooks with pagination.

    Args:
        is_active: Filter by active status
        limit: Maximum number of results
        offset: Number of results to skip
        session: Database session

    Returns:
        Paginated list of webhooks
    """
    service = WebhookService(session)
    webhooks, total = await service.list_webhooks(
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    return WebhookList(
        items=[WebhookRead.model_validate(webhook) for webhook in webhooks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{webhook_id}",
    response_model=WebhookRead,
    summary="Get a webhook",
    description="Fetch a webhook by its identifier.",
    responses={404: {"description": "Webhook not found"}},
)
async def get_webhook(
    webhook_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookRead:
    """Get a single webhook by ID.

    Args:
        webhook_id: Webhook UUID
        session: Database session

    Returns:
        Webhook details

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(session)
    webhook = await service.get_webhook(webhook_id)

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    return WebhookRead.model_validate(webhook)


@router.patch(
    "/{webhook_id}",
    response_model=WebhookRead,
    summary="Update a webhook",
    description="Update an existing webhook configuration.",
    responses={404: {"description": "Webhook not found"}},
)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookRead:
    """Update an existing webhook.

    Args:
        webhook_id: Webhook UUID
        payload: Update payload
        session: Database session

    Returns:
        Updated webhook

    Raises:
        HTTPException: If webhook not found or validation fails
    """
    # Track business metrics
    track_user_action("update", is_authenticated=False)

    service = WebhookService(session)

    try:
        webhook = await service.update_webhook(webhook_id, payload)
        if webhook is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook {webhook_id} not found",
            )

        await session.commit()
        return WebhookRead.model_validate(webhook)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook",
    description="Permanently delete a webhook and its delivery history.",
    responses={404: {"description": "Webhook not found"}},
)
async def delete_webhook(
    webhook_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a webhook permanently.

    Args:
        webhook_id: Webhook UUID
        session: Database session

    Raises:
        HTTPException: If webhook not found
    """
    # Track business metrics
    track_user_action("delete", is_authenticated=False)

    service = WebhookService(session)
    deleted = await service.delete_webhook(webhook_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    await session.commit()

    # INFO - permanent data removal (audit trail)
    logger.info(
        "Webhook deleted via API",
        extra={"webhook_id": str(webhook_id), "operation": "endpoint.delete_webhook"},
    )


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    summary="Test a webhook",
    description="Send a test event to the webhook URL.",
    responses={404: {"description": "Webhook not found"}},
)
async def test_webhook(
    webhook_id: UUID,
    test_request: WebhookTestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookTestResponse:
    """Test webhook by sending a test event.

    Args:
        webhook_id: Webhook UUID
        test_request: Test request payload
        session: Database session

    Returns:
        Test result with delivery status

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(session)
    webhook = await service.get_webhook(webhook_id)

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    # Create test delivery record
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event_type=test_request.event_type,
        event_id="test-" + str(UUID()),
        payload=test_request.payload or {"test": True},
        status="pending",
        attempt_count=0,
        max_attempts=1,
    )

    from example_service.features.webhooks.repository import get_webhook_delivery_repository
    delivery_repo = get_webhook_delivery_repository()
    created_delivery = await delivery_repo.create(session, delivery)
    await session.commit()

    # Attempt delivery
    client = WebhookClient(timeout_seconds=webhook.timeout_seconds)
    result = await client.deliver(
        webhook=webhook,
        event_type=test_request.event_type,
        event_id=created_delivery.event_id,
        payload=created_delivery.payload,
    )

    # Update delivery record
    await delivery_repo.update_status(
        session,
        created_delivery.id,
        "delivered" if result.success else "failed",
        response_status_code=result.status_code,
        response_body=result.response_body,
        response_time_ms=result.response_time_ms,
        error_message=result.error_message,
    )
    await session.commit()

    # INFO - test delivery (useful for debugging)
    logger.info(
        "Webhook test delivery",
        extra={
            "webhook_id": str(webhook_id),
            "delivery_id": str(created_delivery.id),
            "success": result.success,
            "status_code": result.status_code,
            "operation": "endpoint.test_webhook",
        },
    )

    return WebhookTestResponse(
        success=result.success,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_message=result.error_message,
        delivery_id=created_delivery.id,
    )


@router.post(
    "/{webhook_id}/regenerate-secret",
    response_model=SecretRegenerateResponse,
    summary="Regenerate webhook secret",
    description="Generate a new HMAC secret for webhook signature verification.",
    responses={404: {"description": "Webhook not found"}},
)
async def regenerate_secret(
    webhook_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SecretRegenerateResponse:
    """Regenerate HMAC secret for a webhook.

    Args:
        webhook_id: Webhook UUID
        session: Database session

    Returns:
        New secret

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(session)
    webhook = await service.regenerate_secret(webhook_id)

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    await session.commit()

    return SecretRegenerateResponse(
        webhook_id=webhook.id,
        secret=webhook.secret,
    )


@router.get(
    "/{webhook_id}/deliveries",
    response_model=WebhookDeliveryList,
    summary="List webhook deliveries",
    description="List delivery history for a specific webhook.",
    responses={404: {"description": "Webhook not found"}},
)
async def list_deliveries(
    webhook_id: UUID,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookDeliveryList:
    """List delivery history for a webhook.

    Args:
        webhook_id: Webhook UUID
        limit: Maximum number of results
        offset: Number of results to skip
        session: Database session

    Returns:
        Paginated list of deliveries

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(session)
    webhook = await service.get_webhook(webhook_id)

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    deliveries, total = await service.list_deliveries(
        webhook_id,
        limit=limit,
        offset=offset,
    )

    return WebhookDeliveryList(
        items=[WebhookDeliveryRead.model_validate(delivery) for delivery in deliveries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{webhook_id}/deliveries/{delivery_id}/retry",
    response_model=WebhookDeliveryRead,
    summary="Retry a failed delivery",
    description="Manually retry a failed webhook delivery.",
    responses={404: {"description": "Webhook or delivery not found"}},
)
async def retry_delivery(
    webhook_id: UUID,
    delivery_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookDeliveryRead:
    """Manually retry a failed delivery.

    Args:
        webhook_id: Webhook UUID
        delivery_id: Delivery UUID
        session: Database session

    Returns:
        Updated delivery record

    Raises:
        HTTPException: If webhook or delivery not found
    """
    service = WebhookService(session)

    # Verify webhook exists
    webhook = await service.get_webhook(webhook_id)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    # Get and retry delivery
    delivery = await service.retry_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {delivery_id} not found",
        )

    # Verify delivery belongs to this webhook
    if delivery.webhook_id != webhook_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {delivery_id} does not belong to webhook {webhook_id}",
        )

    await session.commit()

    return WebhookDeliveryRead.model_validate(delivery)
