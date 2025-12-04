"""Multi-tenant event hierarchy for domain events.

This module provides event base classes for multi-tenant applications
with header-based routing for websocket dispatch and message filtering.

Event Hierarchy:
    DomainEvent
    └── ServiceEvent        # Internal service events (no websocket dispatch)
        └── TenantEvent     # Tenant-wide events (broadcast to all tenant users)
            ├── UserEvent   # Single user events (targeted delivery)
            └── MultiUserEvent  # Multiple user events (group delivery)

Header-Based Routing:
    - TenantEvent: Sets "user_uuid:*" for broadcast to all tenant users
    - UserEvent: Sets "x-user-uuid" for targeted delivery to single user
    - MultiUserEvent: Sets "x-user-uuids" for delivery to multiple users

Usage:
    class OrderCreatedEvent(TenantEvent):
        event_type: ClassVar[str] = "order.created"
        order_id: str
        amount: Decimal

    class UserNotificationEvent(UserEvent):
        event_type: ClassVar[str] = "user.notification"
        message: str

    class TeamAlertEvent(MultiUserEvent):
        event_type: ClassVar[str] = "team.alert"
        alert_type: str
        team_id: str
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from .base import DomainEvent


class ServiceEvent(DomainEvent):
    """Service-level event base class.

    These events are intended for internal service-to-service communication
    and should NOT be dispatched to websocket clients. Use this for:
    - Internal system events (health checks, config changes)
    - Service coordination events
    - Background job triggers

    Example:
        class CacheInvalidatedEvent(ServiceEvent):
            event_type: ClassVar[str] = "cache.invalidated"
            cache_key: str
    """

    event_type: ClassVar[str] = "domain.event"


class TenantEvent(ServiceEvent):
    """Tenant-level event base class.

    These events are scoped to a specific tenant and broadcast to ALL
    users of that tenant via the "user_uuid:*" header. Use this for:
    - Tenant-wide announcements
    - Configuration changes affecting all users
    - Dashboard updates

    The "user_uuid:*" header pattern allows websocket bridges to dispatch
    messages to all connected users for the tenant.

    Attributes:
        tenant_uuid: UUID of the tenant this event belongs to.

    Example:
        class TenantSettingsUpdatedEvent(TenantEvent):
            event_type: ClassVar[str] = "tenant.settings.updated"
            setting_name: str
            new_value: str

        # Publish
        event = TenantSettingsUpdatedEvent(
            tenant_uuid="tenant-123",
            setting_name="theme",
            new_value="dark"
        )
        # Headers will include {"user_uuid:*": True, "x-tenant-uuid": "tenant-123"}
    """

    event_type: ClassVar[str] = "domain.event"

    tenant_uuid: str = Field(
        description="UUID of the tenant this event belongs to.",
    )

    def headers(self) -> dict[str, Any]:
        """Generate headers with tenant-wide broadcast marker.

        Includes "user_uuid:*" to signal broadcast to all tenant users.

        Returns:
            Headers with tenant context and broadcast marker.
        """
        headers = super().headers()
        headers["x-tenant-uuid"] = self.tenant_uuid
        # Broadcast to all users in the tenant
        headers["user_uuid:*"] = True
        return headers


class UserEvent(TenantEvent):
    """User-level event base class.

    These events are scoped to a specific user within a tenant and
    delivered only to that user via the "x-user-uuid" header. Use this for:
    - User notifications
    - Personal data updates
    - Session-specific events

    Removes the "user_uuid:*" broadcast marker and sets specific user routing.

    Attributes:
        tenant_uuid: UUID of the tenant.
        user_uuid: UUID of the target user (optional for system-generated events).

    Example:
        class UserBalanceUpdatedEvent(UserEvent):
            event_type: ClassVar[str] = "user.balance.updated"
            new_balance: Decimal

        # Publish
        event = UserBalanceUpdatedEvent(
            tenant_uuid="tenant-123",
            user_uuid="user-456",
            new_balance=Decimal("100.00")
        )
        # Headers will include {"x-user-uuid": "user-456", "x-tenant-uuid": "tenant-123"}
    """

    event_type: ClassVar[str] = "domain.event"

    user_uuid: str | None = Field(
        default=None,
        description="UUID of the target user for this event.",
    )

    def headers(self) -> dict[str, Any]:
        """Generate headers with user-specific routing.

        Removes tenant broadcast marker and sets targeted user delivery.

        Returns:
            Headers with user routing context.
        """
        headers = super().headers()
        # Remove tenant-wide broadcast (not for single-user events)
        headers.pop("user_uuid:*", None)
        # Set specific user routing
        if self.user_uuid:
            headers["x-user-uuid"] = self.user_uuid
        return headers


class MultiUserEvent(TenantEvent):
    """Multi-user event base class.

    These events are scoped to multiple specific users within a tenant.
    Use this for:
    - Team notifications
    - Group messages
    - Shared resource updates

    The user UUIDs are stored as a comma-separated list in headers for
    efficient routing without creating individual messages.

    Attributes:
        tenant_uuid: UUID of the tenant.
        user_uuids: List of UUIDs for target users.

    Example:
        class TeamMessageEvent(MultiUserEvent):
            event_type: ClassVar[str] = "team.message"
            team_id: str
            message: str

        # Publish
        event = TeamMessageEvent(
            tenant_uuid="tenant-123",
            user_uuids=["user-1", "user-2", "user-3"],
            team_id="team-abc",
            message="Meeting at 3pm"
        )
        # Headers will include {"x-user-uuids": "user-1,user-2,user-3", "x-tenant-uuid": "tenant-123"}
    """

    event_type: ClassVar[str] = "domain.event"

    user_uuids: list[str] = Field(
        default_factory=list,
        description="List of user UUIDs to receive this event.",
    )

    def headers(self) -> dict[str, Any]:
        """Generate headers with multi-user routing.

        Removes tenant broadcast marker and sets multiple user targets.

        Returns:
            Headers with multi-user routing context.
        """
        headers = super().headers()
        # Remove tenant-wide broadcast (not for multi-user events)
        headers.pop("user_uuid:*", None)
        # Set multi-user routing as comma-separated list
        if self.user_uuids:
            headers["x-user-uuids"] = ",".join(self.user_uuids)
        return headers


__all__ = [
    "MultiUserEvent",
    "ServiceEvent",
    "TenantEvent",
    "UserEvent",
]
