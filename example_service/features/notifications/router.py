"""API router for the notifications feature.

This module provides REST API endpoints for managing notifications:

User Endpoints:
- GET /notifications - List user's notifications
- GET /notifications/{notification_id} - Get single notification with deliveries
- POST /notifications/{notification_id}/mark-read - Mark as read
- DELETE /notifications/{notification_id} - Delete notification

Preference Endpoints:
- GET /notifications/preferences - List user's preferences
- GET /notifications/preferences/{notification_type} - Get specific preference
- PUT /notifications/preferences/{notification_type} - Update preference

Admin Endpoints:
- GET /notifications/admin/deliveries - List all deliveries with filters
- POST /notifications/admin/deliveries/{delivery_id}/retry - Manual retry
- GET /notifications/admin/stats - Delivery statistics
- GET /notifications/admin/templates - List templates
- POST /notifications/admin/templates - Create template
- PUT /notifications/admin/templates/{id} - Update template
- POST /notifications/admin/templates/{id}/preview - Preview rendering
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from example_service.core.dependencies.auth import AuthUserDep, require_acl
from example_service.features.notifications.dependencies import (
    CurrentUserIdDep,
    NotificationDeliveryRepositoryDep,
    NotificationRepositoryDep,
    NotificationServiceDep,
    NotificationTemplateServiceDep,
    SessionDep,
    UserNotificationPreferenceRepositoryDep,
)
from example_service.features.notifications.models import (
    NotificationDelivery,
    NotificationTemplate,
    UserNotificationPreference,
)
from example_service.features.notifications.schemas import (
    NotificationDeliveryListResponse,
    NotificationDeliveryResponse,
    NotificationListResponse,
    NotificationResponse,
    NotificationStats,
    NotificationTemplateCreate,
    NotificationTemplateListResponse,
    NotificationTemplateResponse,
    NotificationTemplateUpdate,
    NotificationWithDeliveriesResponse,
    TemplateRenderRequest,
    TemplateRenderResponse,
    UserNotificationPreferenceListResponse,
    UserNotificationPreferenceResponse,
    UserNotificationPreferenceUpdate,
)
from example_service.infra.logging import get_lazy_logger
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(
    UUID,
    CurrentUserIdDep,
    NotificationDeliveryRepositoryDep,
    NotificationRepositoryDep,
    NotificationServiceDep,
    NotificationTemplateServiceDep,
    SessionDep,
    UserNotificationPreferenceRepositoryDep,
)

logger = logging.getLogger(__name__)
lazy_logger = get_lazy_logger(__name__)

# Main router for user endpoints
router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
)

# Admin router for admin-only endpoints
admin_router = APIRouter(
    prefix="/notifications/admin",
    tags=["notifications-admin"],
    dependencies=[Depends(require_acl("notifications.admin"))],
)


# ============================================================================
# User Endpoints - Notifications
# ============================================================================


@router.get(
    "/",
    response_model=NotificationListResponse,
    summary="List user's notifications",
    description="""
List notifications for the authenticated user.

**Query Parameters:**
- `notification_type`: Filter by notification type (e.g., 'reminder', 'file')
- `unread_only`: Only return unread notifications (default: false)
- `limit`: Maximum results (1-100, default: 50)
- `offset`: Pagination offset (default: 0)

**Response includes:**
- List of notifications
- Total count
- Unread count
""",
)
async def list_notifications(
    user_id: CurrentUserIdDep,
    session: SessionDep,
    service: NotificationServiceDep,
    notification_type: Annotated[
        str | None,
        Query(description="Filter by notification type"),
    ] = None,
    unread_only: Annotated[
        bool,
        Query(description="Only return unread notifications"),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum results")] = 50,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
) -> NotificationListResponse:
    """List notifications for the authenticated user."""
    notifications, total, unread_count = await service.list_user_notifications(
        session,
        user_id,
        notification_type=notification_type,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )

    return NotificationListResponse(
        notifications=[
            NotificationResponse.model_validate(notif) for notif in notifications
        ],
        total=total,
        unread_count=unread_count,
    )


@router.get(
    "/{notification_id}",
    response_model=NotificationWithDeliveriesResponse,
    summary="Get single notification with deliveries",
    description="""
Get a notification by ID including all delivery records.

**Authorization:** User must own the notification.

**Returns:**
- Notification details
- List of delivery attempts for each channel
- Delivery status and error information
""",
    responses={
        404: {"description": "Notification not found"},
        403: {"description": "Not authorized to access this notification"},
    },
)
async def get_notification(
    notification_id: UUID,
    user_id: CurrentUserIdDep,
    session: SessionDep,
    repo: NotificationRepositoryDep,
    delivery_repo: NotificationDeliveryRepositoryDep,
) -> NotificationWithDeliveriesResponse:
    """Get a single notification with delivery details."""
    notification = await repo.get(session, notification_id)

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    # Verify ownership
    if notification.user_id != user_id:
        logger.warning(
            f"User {user_id} attempted to access notification {notification_id} (belongs to {notification.user_id})",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this notification",
        )

    # Get deliveries
    deliveries = await delivery_repo.list_for_notification(session, notification_id)

    return NotificationWithDeliveriesResponse(
        **NotificationResponse.model_validate(notification).model_dump(),
        deliveries=[
            NotificationDeliveryResponse.model_validate(delivery)
            for delivery in deliveries
        ],
    )


@router.post(
    "/{notification_id}/mark-read",
    response_model=NotificationResponse,
    summary="Mark notification as read",
    description="""
Mark a notification as read for in-app notifications.

**Authorization:** User must own the notification.

Sets the `read` flag to true and records `read_at` timestamp.
""",
    responses={
        404: {"description": "Notification not found"},
        403: {"description": "Not authorized to access this notification"},
    },
)
async def mark_notification_read(
    notification_id: UUID,
    user_id: CurrentUserIdDep,
    session: SessionDep,
    service: NotificationServiceDep,
) -> NotificationResponse:
    """Mark a notification as read."""
    notification = await service.mark_as_read(session, notification_id, user_id)

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found or not authorized",
        )

    await session.commit()

    return NotificationResponse.model_validate(notification)


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete notification",
    description="""
Delete a notification permanently.

**Authorization:** User must own the notification.

This also deletes associated delivery records (cascade).
""",
    responses={
        404: {"description": "Notification not found"},
        403: {"description": "Not authorized to delete this notification"},
    },
)
async def delete_notification(
    notification_id: UUID,
    user_id: CurrentUserIdDep,
    session: SessionDep,
    repo: NotificationRepositoryDep,
) -> None:
    """Delete a notification permanently."""
    notification = await repo.get(session, notification_id)

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    # Verify ownership
    if notification.user_id != user_id:
        logger.warning(
            f"User {user_id} attempted to delete notification {notification_id} (belongs to {notification.user_id})",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this notification",
        )

    await session.delete(notification)
    await session.commit()

    logger.info(
        f"Notification deleted: {notification_id} by user {user_id}",
        extra={"notification_id": str(notification_id), "user_id": user_id},
    )


# ============================================================================
# User Endpoints - Preferences
# ============================================================================


@router.get(
    "/preferences",
    response_model=UserNotificationPreferenceListResponse,
    summary="List user's notification preferences",
    description="""
List all notification preferences for the authenticated user.

**Returns:**
- Preferences for all notification types
- Enabled channels per type
- Quiet hours configuration
- Channel-specific settings
""",
)
async def list_preferences(
    user_id: CurrentUserIdDep,
    session: SessionDep,
    repo: UserNotificationPreferenceRepositoryDep,
) -> UserNotificationPreferenceListResponse:
    """List all notification preferences for the user."""
    preferences = await repo.list_for_user(session, user_id)

    return UserNotificationPreferenceListResponse(
        preferences=[
            UserNotificationPreferenceResponse.model_validate(pref)
            for pref in preferences
        ],
        total=len(preferences),
    )


@router.get(
    "/preferences/{notification_type}",
    response_model=UserNotificationPreferenceResponse,
    summary="Get preference for specific notification type",
    description="""
Get notification preferences for a specific notification type.

**Returns:**
- Enabled channels
- Quiet hours
- Channel-specific settings
- Activity status
""",
    responses={
        404: {"description": "Preference not found for this notification type"},
    },
)
async def get_preference(
    notification_type: str,
    user_id: CurrentUserIdDep,
    session: SessionDep,
    repo: UserNotificationPreferenceRepositoryDep,
) -> UserNotificationPreferenceResponse:
    """Get preference for a specific notification type."""
    preference = await repo.get_for_user_and_type(session, user_id, notification_type)

    if not preference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preference not found for notification type: {notification_type}",
        )

    return UserNotificationPreferenceResponse.model_validate(preference)


@router.put(
    "/preferences/{notification_type}",
    response_model=UserNotificationPreferenceResponse,
    summary="Update notification preference",
    description="""
Update notification preferences for a specific type.

**Update fields:**
- `enabled_channels`: List of channels to enable (email, webhook, websocket, in_app)
- `channel_settings`: Channel-specific configuration
- `quiet_hours_start`: Start hour for quiet period (0-23, UTC)
- `quiet_hours_end`: End hour for quiet period (0-23, UTC)
- `is_active`: Enable/disable notifications for this type

Creates preference if it doesn't exist.
""",
)
async def update_preference(
    notification_type: str,
    payload: UserNotificationPreferenceUpdate,
    user_id: CurrentUserIdDep,
    session: SessionDep,
    repo: UserNotificationPreferenceRepositoryDep,
) -> UserNotificationPreferenceResponse:
    """Update or create notification preference for a type."""
    preference = await repo.get_for_user_and_type(session, user_id, notification_type)

    if not preference:
        # Create new preference
        preference = UserNotificationPreference(
            user_id=user_id,
            notification_type=notification_type,
            enabled_channels=payload.enabled_channels or ["email", "websocket"],
            channel_settings=payload.channel_settings,
            quiet_hours_start=payload.quiet_hours_start,
            quiet_hours_end=payload.quiet_hours_end,
            is_active=payload.is_active if payload.is_active is not None else True,
        )
        session.add(preference)
    else:
        # Update existing preference
        if payload.enabled_channels is not None:
            preference.enabled_channels = payload.enabled_channels
        if payload.channel_settings is not None:
            preference.channel_settings = payload.channel_settings
        if payload.quiet_hours_start is not None:
            preference.quiet_hours_start = payload.quiet_hours_start
        if payload.quiet_hours_end is not None:
            preference.quiet_hours_end = payload.quiet_hours_end
        if payload.is_active is not None:
            preference.is_active = payload.is_active

    await session.commit()
    await session.refresh(preference)

    logger.info(
        f"Notification preference updated: {notification_type} for user {user_id}",
        extra={
            "notification_type": notification_type,
            "user_id": user_id,
            "enabled_channels": preference.enabled_channels,
        },
    )

    return UserNotificationPreferenceResponse.model_validate(preference)


# ============================================================================
# Admin Endpoints - Deliveries
# ============================================================================


@admin_router.get(
    "/deliveries",
    response_model=NotificationDeliveryListResponse,
    summary="List all deliveries (admin)",
    description="""
List notification deliveries with filtering (admin only).

**Query Parameters:**
- `channel`: Filter by channel (email, webhook, websocket, in_app)
- `status`: Filter by status (pending, delivered, failed, retrying)
- `limit`: Maximum results (1-200, default: 50)
- `offset`: Pagination offset (default: 0)

**Requires:** `notifications.admin` ACL permission.
""",
)
async def list_deliveries_admin(
    session: SessionDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
    channel: Annotated[
        str | None,
        Query(description="Filter by channel"),
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum results")] = 50,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
) -> NotificationDeliveryListResponse:
    """List all notification deliveries with filters (admin)."""
    stmt = select(NotificationDelivery)

    # Apply filters
    if channel:
        stmt = stmt.where(NotificationDelivery.channel == channel)
    if status_filter:
        stmt = stmt.where(NotificationDelivery.status == status_filter)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Apply pagination and ordering
    stmt = stmt.order_by(NotificationDelivery.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    deliveries = result.scalars().all()

    return NotificationDeliveryListResponse(
        deliveries=[
            NotificationDeliveryResponse.model_validate(delivery)
            for delivery in deliveries
        ],
        total=total,
    )


@admin_router.post(
    "/deliveries/{delivery_id}/retry",
    response_model=NotificationDeliveryResponse,
    summary="Manually retry delivery (admin)",
    description="""
Manually retry a failed delivery (admin only).

Resets the delivery to 'pending' status and clears error information.
The background worker will pick it up for retry.

**Requires:** `notifications.admin` ACL permission.
""",
    responses={
        404: {"description": "Delivery not found"},
    },
)
async def retry_delivery_admin(
    delivery_id: UUID,
    session: SessionDep,
    delivery_repo: NotificationDeliveryRepositoryDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
) -> NotificationDeliveryResponse:
    """Manually retry a delivery (admin)."""
    delivery = await delivery_repo.get(session, delivery_id)

    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {delivery_id} not found",
        )

    # Reset for retry
    delivery.status = "pending"
    delivery.next_retry_at = None
    delivery.error_message = None
    delivery.error_category = None

    await session.commit()
    await session.refresh(delivery)

    logger.info(
        f"Delivery manually retried: {delivery_id}",
        extra={"delivery_id": str(delivery_id)},
    )

    return NotificationDeliveryResponse.model_validate(delivery)


@admin_router.get(
    "/stats",
    response_model=NotificationStats,
    summary="Get notification statistics (admin)",
    description="""
Get comprehensive notification delivery statistics (admin only).

**Returns:**
- Total notifications
- Total deliveries
- Deliveries by channel (email, webhook, etc.)
- Deliveries by status (delivered, failed, etc.)
- Average response time
- Failed deliveries count

**Requires:** `notifications.admin` ACL permission.
""",
)
async def get_stats_admin(
    session: SessionDep,
    delivery_repo: NotificationDeliveryRepositoryDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
) -> NotificationStats:
    """Get notification delivery statistics (admin)."""
    # Total notifications
    notif_count_stmt = select(func.count()).select_from(
        select(NotificationDelivery.notification_id).distinct().subquery(),
    )
    notif_count_result = await session.execute(notif_count_stmt)
    total_notifications = notif_count_result.scalar_one()

    # Total deliveries
    delivery_count_stmt = select(func.count()).select_from(NotificationDelivery)
    delivery_count_result = await session.execute(delivery_count_stmt)
    total_deliveries = delivery_count_result.scalar_one()

    # Deliveries by channel
    channel_stmt = select(
        NotificationDelivery.channel,
        func.count(NotificationDelivery.id).label("count"),
    ).group_by(NotificationDelivery.channel)
    channel_result = await session.execute(channel_stmt)
    deliveries_by_channel = {row.channel: row.count for row in channel_result}

    # Deliveries by status
    status_stmt = select(
        NotificationDelivery.status,
        func.count(NotificationDelivery.id).label("count"),
    ).group_by(NotificationDelivery.status)
    status_result = await session.execute(status_stmt)
    deliveries_by_status = {row.status: row.count for row in status_result}

    # Average response time (only for completed deliveries)
    avg_time_stmt = select(
        func.avg(NotificationDelivery.response_time_ms),
    ).where(NotificationDelivery.response_time_ms.isnot(None))
    avg_time_result = await session.execute(avg_time_stmt)
    avg_response_time = avg_time_result.scalar_one()

    # Failed deliveries count
    failed_count_stmt = (
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.status == "failed")
    )
    failed_count_result = await session.execute(failed_count_stmt)
    failed_deliveries_count = failed_count_result.scalar_one()

    return NotificationStats(
        total_notifications=total_notifications,
        total_deliveries=total_deliveries,
        deliveries_by_channel=deliveries_by_channel,
        deliveries_by_status=deliveries_by_status,
        average_response_time_ms=avg_response_time,
        failed_deliveries_count=failed_deliveries_count,
    )


# ============================================================================
# Admin Endpoints - Templates
# ============================================================================


@admin_router.get(
    "/templates",
    response_model=NotificationTemplateListResponse,
    summary="List notification templates (admin)",
    description="""
List all notification templates (admin only).

**Query Parameters:**
- `notification_type`: Filter by type
- `channel`: Filter by channel
- `is_active`: Filter by active status

**Requires:** `notifications.admin` ACL permission.
""",
)
async def list_templates_admin(
    session: SessionDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
    notification_type: Annotated[
        str | None, Query(description="Filter by notification type"),
    ] = None,
    channel: Annotated[str | None, Query(description="Filter by channel")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
) -> NotificationTemplateListResponse:
    """List all notification templates (admin)."""
    stmt = select(NotificationTemplate)

    # Apply filters
    if notification_type:
        stmt = stmt.where(NotificationTemplate.notification_type == notification_type)
    if channel:
        stmt = stmt.where(NotificationTemplate.channel == channel)
    if is_active is not None:
        stmt = stmt.where(NotificationTemplate.is_active == is_active)

    stmt = stmt.order_by(
        NotificationTemplate.notification_type.asc(),
        NotificationTemplate.channel.asc(),
    )

    result = await session.execute(stmt)
    templates = result.scalars().all()

    return NotificationTemplateListResponse(
        templates=[
            NotificationTemplateResponse.model_validate(template)
            for template in templates
        ],
        total=len(templates),
    )


@admin_router.post(
    "/templates",
    response_model=NotificationTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create notification template (admin)",
    description="""
Create a new notification template (admin only).

**Template types by channel:**
- **Email**: Requires `subject_template`, `body_template`, optionally `body_html_template`
- **Webhook**: Requires `webhook_payload_template`
- **WebSocket**: Requires `websocket_event_type`, `websocket_payload_template`
- **In-App**: Uses `body_template` for text content

All templates use Jinja2 syntax for variable substitution.

**Requires:** `notifications.admin` ACL permission.
""",
)
async def create_template_admin(
    payload: NotificationTemplateCreate,
    session: SessionDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
) -> NotificationTemplateResponse:
    """Create a new notification template (admin)."""
    template = NotificationTemplate(
        name=payload.name,
        notification_type=payload.notification_type,
        channel=payload.channel,
        description=payload.description,
        priority=payload.priority,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        body_html_template=payload.body_html_template,
        webhook_payload_template=payload.webhook_payload_template,
        websocket_event_type=payload.websocket_event_type,
        websocket_payload_template=payload.websocket_payload_template,
        required_context_vars=payload.required_context_vars,
        is_active=payload.is_active,
        version=1,
    )

    session.add(template)
    await session.commit()
    await session.refresh(template)

    logger.info(
        f"Notification template created: {template.name} ({template.notification_type}/{template.channel})",
        extra={
            "template_id": str(template.id),
            "notification_type": template.notification_type,
            "channel": template.channel,
        },
    )

    return NotificationTemplateResponse.model_validate(template)


@admin_router.put(
    "/templates/{template_id}",
    response_model=NotificationTemplateResponse,
    summary="Update notification template (admin)",
    description="""
Update an existing notification template (admin only).

Only provided fields will be updated. Version is auto-incremented.

**Requires:** `notifications.admin` ACL permission.
""",
    responses={
        404: {"description": "Template not found"},
    },
)
async def update_template_admin(
    template_id: UUID,
    payload: NotificationTemplateUpdate,
    session: SessionDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
) -> NotificationTemplateResponse:
    """Update an existing notification template (admin)."""
    stmt = select(NotificationTemplate).where(NotificationTemplate.id == template_id)
    result = await session.execute(stmt)
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found",
        )

    # Update fields
    if payload.description is not None:
        template.description = payload.description
    if payload.is_active is not None:
        template.is_active = payload.is_active
    if payload.priority is not None:
        template.priority = payload.priority
    if payload.subject_template is not None:
        template.subject_template = payload.subject_template
    if payload.body_template is not None:
        template.body_template = payload.body_template
    if payload.body_html_template is not None:
        template.body_html_template = payload.body_html_template
    if payload.webhook_payload_template is not None:
        template.webhook_payload_template = payload.webhook_payload_template
    if payload.websocket_event_type is not None:
        template.websocket_event_type = payload.websocket_event_type
    if payload.websocket_payload_template is not None:
        template.websocket_payload_template = payload.websocket_payload_template
    if payload.required_context_vars is not None:
        template.required_context_vars = payload.required_context_vars

    # Increment version
    template.version += 1

    await session.commit()
    await session.refresh(template)

    logger.info(
        f"Notification template updated: {template.name} (version {template.version})",
        extra={"template_id": str(template_id), "version": template.version},
    )

    return NotificationTemplateResponse.model_validate(template)


@admin_router.post(
    "/templates/{template_id}/preview",
    response_model=TemplateRenderResponse,
    summary="Preview template rendering (admin)",
    description="""
Preview template rendering with provided context (admin only).

**Use this to:**
- Test templates before activating them
- Validate context variables
- Preview output with sample data

Does not send any notifications or create deliveries.

**Requires:** `notifications.admin` ACL permission.
""",
    responses={
        404: {"description": "Template not found"},
        422: {"description": "Template rendering failed"},
    },
)
async def preview_template_admin(
    template_id: UUID,
    payload: TemplateRenderRequest,
    session: SessionDep,
    template_service: NotificationTemplateServiceDep,
    _user: Annotated[AuthUserDep, Depends(require_acl("notifications.admin"))],
) -> TemplateRenderResponse:
    """Preview template rendering with context (admin)."""
    try:
        rendered = await template_service.render_template(
            session, template_id, payload.context,
        )

        return TemplateRenderResponse(
            rendered_subject=rendered.get("subject"),
            rendered_body=rendered.get("body"),
            rendered_body_html=rendered.get("body_html"),
            rendered_payload=rendered.get("payload"),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Template rendering failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template rendering failed: {e!s}",
        ) from e


# Export both routers
__all__ = ["admin_router", "router"]
