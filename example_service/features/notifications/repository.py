"""Repositories for the notifications feature."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select

from example_service.core.database.repository import BaseRepository
from example_service.features.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationTemplate,
    UserNotificationPreference,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class NotificationTemplateRepository(BaseRepository[NotificationTemplate]):
    """Repository for NotificationTemplate model.

    Provides CRUD operations and queries for notification templates.
    Supports tenant-aware template resolution with tenant override > global fallback.
    """

    def __init__(self) -> None:
        """Initialize with NotificationTemplate model."""
        super().__init__(NotificationTemplate)

    async def get_by_name_and_channel(
        self,
        session: AsyncSession,
        name: str,
        channel: str,
        tenant_id: str | None = None,
    ) -> NotificationTemplate | None:
        """Get template by name and channel with tenant-aware resolution.

        Lookup order:
        1. Tenant-specific template (if tenant_id provided)
        2. Global template (tenant_id = None)

        Args:
            session: Database session
            name: Template name (e.g., 'reminder_due')
            channel: Delivery channel (email, webhook, websocket, in_app)
            tenant_id: Optional tenant ID for tenant-specific templates

        Returns:
            Template if found, None otherwise
        """
        # Try tenant-specific first if tenant_id provided
        if tenant_id:
            stmt = select(NotificationTemplate).where(
                and_(
                    NotificationTemplate.name == name,
                    NotificationTemplate.channel == channel,
                    NotificationTemplate.tenant_id == tenant_id,
                    NotificationTemplate.is_active.is_(True),
                ),
            )
            result = await session.execute(stmt)
            template = result.scalar_one_or_none()
            if template:
                self._lazy.debug(lambda: f"db.get_template({name=}, {channel=}, {tenant_id=}) -> tenant template")
                return template

        # Fall back to global template
        stmt = select(NotificationTemplate).where(
            and_(
                NotificationTemplate.name == name,
                NotificationTemplate.channel == channel,
                NotificationTemplate.tenant_id.is_(None),
                NotificationTemplate.is_active.is_(True),
            ),
        )
        result = await session.execute(stmt)
        template = result.scalar_one_or_none()

        self._lazy.debug(lambda: f"db.get_template({name=}, {channel=}, {tenant_id=}) -> {'global template' if template else 'not found'}")
        return template

    async def list_by_type(
        self,
        session: AsyncSession,
        notification_type: str,
        tenant_id: str | None = None,
    ) -> Sequence[NotificationTemplate]:
        """List all active templates for a notification type.

        Args:
            session: Database session
            notification_type: Type of notification (e.g., 'reminder')
            tenant_id: Optional tenant ID filter

        Returns:
            Sequence of templates
        """
        stmt = select(NotificationTemplate).where(
            and_(
                NotificationTemplate.notification_type == notification_type,
                NotificationTemplate.is_active.is_(True),
            ),
        )

        if tenant_id:
            stmt = stmt.where(
                or_(
                    NotificationTemplate.tenant_id == tenant_id,
                    NotificationTemplate.tenant_id.is_(None),
                ),
            )
        else:
            stmt = stmt.where(NotificationTemplate.tenant_id.is_(None))

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.list_by_type({notification_type=}, {tenant_id=}) -> {len(items)} templates")
        return items


class UserNotificationPreferenceRepository(BaseRepository[UserNotificationPreference]):
    """Repository for UserNotificationPreference model.

    Provides CRUD operations and queries for user notification preferences.
    """

    def __init__(self) -> None:
        """Initialize with UserNotificationPreference model."""
        super().__init__(UserNotificationPreference)

    async def get_for_user_and_type(
        self,
        session: AsyncSession,
        user_id: str,
        notification_type: str,
        tenant_id: str | None = None,
    ) -> UserNotificationPreference | None:
        """Get preference for a specific user and notification type.

        Args:
            session: Database session
            user_id: User identifier
            notification_type: Type of notification
            tenant_id: Optional tenant ID

        Returns:
            Preference if found, None otherwise
        """
        stmt = select(UserNotificationPreference).where(
            and_(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.notification_type == notification_type,
                UserNotificationPreference.tenant_id == tenant_id,
                UserNotificationPreference.is_active.is_(True),
            ),
        )
        result = await session.execute(stmt)
        pref = result.scalar_one_or_none()

        self._lazy.debug(lambda: f"db.get_preference({user_id=}, {notification_type=}) -> {pref is not None}")
        return pref

    async def list_for_user(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_id: str | None = None,
    ) -> Sequence[UserNotificationPreference]:
        """List all preferences for a user.

        Args:
            session: Database session
            user_id: User identifier
            tenant_id: Optional tenant ID

        Returns:
            Sequence of preferences
        """
        stmt = select(UserNotificationPreference).where(
            and_(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.tenant_id == tenant_id,
                UserNotificationPreference.is_active.is_(True),
            ),
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.list_for_user({user_id=}) -> {len(items)} preferences")
        return items

    async def upsert(
        self,
        session: AsyncSession,
        user_id: str,
        notification_type: str,
        enabled_channels: list[str],
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> UserNotificationPreference:
        """Create or update preference (upsert pattern).

        Args:
            session: Database session
            user_id: User identifier
            notification_type: Type of notification
            enabled_channels: List of enabled channels
            tenant_id: Optional tenant ID
            **kwargs: Additional fields to update

        Returns:
            Created or updated preference
        """
        existing = await self.get_for_user_and_type(session, user_id, notification_type, tenant_id)

        if existing:
            # Update existing
            existing.enabled_channels = enabled_channels
            for key, value in kwargs.items():
                setattr(existing, key, value)
            self._lazy.debug(lambda: f"db.upsert({user_id=}, {notification_type=}) -> updated")
            return existing

        # Create new
        pref = UserNotificationPreference(
            user_id=user_id,
            notification_type=notification_type,
            enabled_channels=enabled_channels,
            tenant_id=tenant_id,
            **kwargs,
        )
        session.add(pref)
        self._lazy.debug(lambda: f"db.upsert({user_id=}, {notification_type=}) -> created")
        return pref


class NotificationRepository(BaseRepository[Notification]):
    """Repository for Notification model.

    Provides CRUD operations and queries for notifications.
    Supports filtering, pagination, and status updates.
    """

    def __init__(self) -> None:
        """Initialize with Notification model."""
        super().__init__(Notification)

    async def list_for_user(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        tenant_id: str | None = None,
        notification_type: str | None = None,
        status: str | None = None,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Notification], int]:
        """List notifications for a user with filters and counts.

        Args:
            session: Database session
            user_id: User identifier
            tenant_id: Optional tenant ID filter
            notification_type: Optional type filter
            status: Optional status filter
            unread_only: Only return unread notifications
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (notifications, total_count)
        """
        # Build base query
        stmt = select(Notification).where(Notification.user_id == user_id)

        if tenant_id is not None:
            stmt = stmt.where(Notification.tenant_id == tenant_id)

        if notification_type:
            stmt = stmt.where(Notification.notification_type == notification_type)

        if status:
            stmt = stmt.where(Notification.status == status)

        if unread_only:
            stmt = stmt.where(Notification.read.is_(False))

        # Count query (before limit/offset)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Apply ordering and pagination
        stmt = stmt.order_by(Notification.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.list_for_user({user_id=}) -> {len(items)}/{total} notifications")
        return items, total

    async def get_unread_count(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_id: str | None = None,
    ) -> int:
        """Get count of unread notifications for a user.

        Args:
            session: Database session
            user_id: User identifier
            tenant_id: Optional tenant ID

        Returns:
            Count of unread notifications
        """
        stmt = select(func.count()).where(
            and_(
                Notification.user_id == user_id,
                Notification.read.is_(False),
            ),
        )

        if tenant_id is not None:
            stmt = stmt.where(Notification.tenant_id == tenant_id)

        result = await session.execute(stmt)
        count = result.scalar() or 0

        self._lazy.debug(lambda: f"db.get_unread_count({user_id=}) -> {count}")
        return count

    async def find_scheduled_pending(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> Sequence[Notification]:
        """Find notifications scheduled for sending (scheduled_for <= now).

        Args:
            session: Database session
            limit: Max results

        Returns:
            Sequence of pending scheduled notifications
        """
        now = datetime.now(UTC)
        stmt = select(Notification).where(
            and_(
                Notification.status == "pending",
                Notification.scheduled_for.isnot(None),
                Notification.scheduled_for <= now,
            ),
        )
        stmt = stmt.order_by(Notification.scheduled_for.asc())
        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.find_scheduled_pending() -> {len(items)} notifications")
        return items

    async def mark_as_read(
        self,
        session: AsyncSession,
        notification_id: UUID,
    ) -> Notification | None:
        """Mark a notification as read.

        Args:
            session: Database session
            notification_id: Notification UUID

        Returns:
            Updated notification if found, None otherwise
        """
        notification = await self.get(session, notification_id)
        if notification:
            notification.read = True
            notification.read_at = datetime.now(UTC)
            self._lazy.debug(lambda: f"db.mark_as_read({notification_id}) -> marked")
        return notification


class NotificationDeliveryRepository(BaseRepository[NotificationDelivery]):
    """Repository for NotificationDelivery model.

    Provides CRUD operations and queries for notification deliveries.
    Supports retry tracking and status updates.
    """

    def __init__(self) -> None:
        """Initialize with NotificationDelivery model."""
        super().__init__(NotificationDelivery)

    async def list_for_notification(
        self,
        session: AsyncSession,
        notification_id: UUID,
    ) -> Sequence[NotificationDelivery]:
        """List all deliveries for a notification.

        Args:
            session: Database session
            notification_id: Notification UUID

        Returns:
            Sequence of deliveries
        """
        stmt = select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notification_id,
        )
        stmt = stmt.order_by(NotificationDelivery.created_at.asc())

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.list_for_notification({notification_id}) -> {len(items)} deliveries")
        return items

    async def find_pending_retries(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> Sequence[NotificationDelivery]:
        """Find deliveries pending retry (next_retry_at <= now).

        Args:
            session: Database session
            limit: Max results

        Returns:
            Sequence of deliveries ready for retry
        """
        now = datetime.now(UTC)
        stmt = select(NotificationDelivery).where(
            and_(
                NotificationDelivery.status.in_(["pending", "retrying"]),
                NotificationDelivery.next_retry_at.isnot(None),
                NotificationDelivery.next_retry_at <= now,
                NotificationDelivery.attempt_count < NotificationDelivery.max_attempts,
            ),
        )
        stmt = stmt.order_by(NotificationDelivery.next_retry_at.asc())
        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.find_pending_retries() -> {len(items)} deliveries")
        return items

    async def get_stats_by_channel(
        self,
        session: AsyncSession,
        channel: str | None = None,
    ) -> dict[str, int]:
        """Get delivery statistics by status.

        Args:
            session: Database session
            channel: Optional channel filter

        Returns:
            Dict mapping status to count
        """
        stmt = select(
            NotificationDelivery.status,
            func.count(NotificationDelivery.id).label("count"),
        )

        if channel:
            stmt = stmt.where(NotificationDelivery.channel == channel)

        stmt = stmt.group_by(NotificationDelivery.status)

        result = await session.execute(stmt)
        stats = {row.status: row.count for row in result}

        self._lazy.debug(lambda: f"db.get_stats_by_channel({channel=}) -> {stats}")
        return stats


# Factory functions for dependency injection
_template_repository: NotificationTemplateRepository | None = None
_preference_repository: UserNotificationPreferenceRepository | None = None
_notification_repository: NotificationRepository | None = None
_delivery_repository: NotificationDeliveryRepository | None = None


def get_notification_template_repository() -> NotificationTemplateRepository:
    """Get NotificationTemplateRepository singleton instance."""
    global _template_repository
    if _template_repository is None:
        _template_repository = NotificationTemplateRepository()
    return _template_repository


def get_user_notification_preference_repository() -> UserNotificationPreferenceRepository:
    """Get UserNotificationPreferenceRepository singleton instance."""
    global _preference_repository
    if _preference_repository is None:
        _preference_repository = UserNotificationPreferenceRepository()
    return _preference_repository


def get_notification_repository() -> NotificationRepository:
    """Get NotificationRepository singleton instance."""
    global _notification_repository
    if _notification_repository is None:
        _notification_repository = NotificationRepository()
    return _notification_repository


def get_notification_delivery_repository() -> NotificationDeliveryRepository:
    """Get NotificationDeliveryRepository singleton instance."""
    global _delivery_repository
    if _delivery_repository is None:
        _delivery_repository = NotificationDeliveryRepository()
    return _delivery_repository
