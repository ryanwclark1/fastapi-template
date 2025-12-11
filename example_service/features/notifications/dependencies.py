"""FastAPI dependencies for notifications feature.

Provides Annotated type aliases for clean dependency injection in route handlers.

Example usage:
    from example_service.features.notifications.dependencies import (
        NotificationServiceDep,
        SessionDep,
        CurrentUserIdDep,
    )

    @router.get("/notifications")
    async def list_notifications(
        user_id: CurrentUserIdDep,
        session: SessionDep,
        service: NotificationServiceDep,
    ) -> NotificationListResponse:
        notifications, total, unread = await service.list_user_notifications(
            session, user_id
        )
        ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.auth import get_auth_user
from example_service.core.dependencies.database import get_db_session
from example_service.core.schemas.auth import AuthUser
from example_service.features.notifications.repository import (
    NotificationDeliveryRepository,
    NotificationRepository,
    UserNotificationPreferenceRepository,
    get_notification_delivery_repository,
    get_notification_repository,
    get_user_notification_preference_repository,
)
from example_service.features.notifications.service import (
    NotificationService,
    get_notification_service,
)
from example_service.features.notifications.templates.service import (
    NotificationTemplateService,
    get_notification_template_service,
)

# Database session dependency
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Auth dependencies
AuthUserDep = Annotated[AuthUser, Depends(get_auth_user)]


def get_current_user_id(user: AuthUserDep) -> str:
    """Extract user ID from authenticated user.

    Args:
        user: Authenticated user from auth dependency

    Returns:
        User identifier string

    Example:
        @router.get("/notifications")
        async def list_notifications(
            user_id: CurrentUserIdDep,
            session: SessionDep,
        ):
            # user_id is a string, ready to use
            ...
    """
    return user.user_id


# Type alias for current user ID
CurrentUserIdDep = Annotated[str, Depends(get_current_user_id)]

# Repository dependencies
NotificationRepositoryDep = Annotated[
    NotificationRepository, Depends(get_notification_repository),
]
NotificationDeliveryRepositoryDep = Annotated[
    NotificationDeliveryRepository, Depends(get_notification_delivery_repository),
]
UserNotificationPreferenceRepositoryDep = Annotated[
    UserNotificationPreferenceRepository,
    Depends(get_user_notification_preference_repository),
]

# Service dependencies
NotificationServiceDep = Annotated[
    NotificationService,
    Depends(get_notification_service),
]
NotificationTemplateServiceDep = Annotated[
    NotificationTemplateService, Depends(get_notification_template_service),
]


__all__ = [
    "AuthUserDep",
    "CurrentUserIdDep",
    "NotificationDeliveryRepositoryDep",
    "NotificationRepositoryDep",
    "NotificationServiceDep",
    "NotificationTemplateServiceDep",
    "SessionDep",
    "UserNotificationPreferenceRepositoryDep",
    "get_current_user_id",
]
