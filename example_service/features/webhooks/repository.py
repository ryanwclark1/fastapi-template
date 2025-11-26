"""Repository for the webhooks feature."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.features.webhooks.models import Webhook, WebhookDelivery

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class WebhookRepository(BaseRepository[Webhook]):
    """Repository for Webhook model.

    Inherits from BaseRepository:
        - get(session, id) -> Webhook | None
        - get_or_raise(session, id) -> Webhook
        - get_by(session, attr, value) -> Webhook | None
        - list(session, limit, offset) -> Sequence[Webhook]
        - search(session, statement, limit, offset) -> SearchResult[Webhook]
        - create(session, instance) -> Webhook
        - create_many(session, instances) -> Sequence[Webhook]
        - delete(session, instance) -> None

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with Webhook model."""
        super().__init__(Webhook)

    async def find_active(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Webhook]:
        """Find all active webhooks.

        Args:
            session: Database session
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of active webhooks, ordered by created_at desc
        """
        stmt = (
            select(Webhook)
            .where(Webhook.is_active == True)  # noqa: E712
            .order_by(Webhook.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.find_active: Webhook(limit={limit}, offset={offset}) -> {len(items)} items"
        )
        return items

    async def find_by_event_type(
        self,
        session: AsyncSession,
        event_type: str,
        *,
        active_only: bool = True,
    ) -> Sequence[Webhook]:
        """Find webhooks subscribed to a specific event type.

        Args:
            session: Database session
            event_type: Event type to filter by
            active_only: Only return active webhooks

        Returns:
            Sequence of webhooks subscribed to the event type
        """
        stmt = select(Webhook).where(Webhook.event_types.contains([event_type]))

        if active_only:
            stmt = stmt.where(Webhook.is_active == True)  # noqa: E712

        stmt = stmt.order_by(Webhook.created_at.desc())

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.find_by_event_type: event_type={event_type!r}, active_only={active_only} -> {len(items)} items"
        )
        return items

    async def search_webhooks(
        self,
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[Webhook]:
        """Search webhooks with filters.

        Args:
            session: Database session
            is_active: Filter by active status
            limit: Page size
            offset: Results to skip

        Returns:
            SearchResult with webhooks and pagination info
        """
        stmt = select(Webhook)

        # Status filter
        if is_active is not None:
            stmt = stmt.where(Webhook.is_active == is_active)

        # Default ordering
        stmt = stmt.order_by(Webhook.created_at.desc())

        search_result = await self.search(session, stmt, limit=limit, offset=offset)

        self._lazy.debug(
            lambda: f"db.search_webhooks: is_active={is_active} -> {len(search_result.items)}/{search_result.total}"
        )
        return search_result


class WebhookDeliveryRepository(BaseRepository[WebhookDelivery]):
    """Repository for WebhookDelivery model.

    Inherits from BaseRepository:
        - get(session, id) -> WebhookDelivery | None
        - get_or_raise(session, id) -> WebhookDelivery
        - get_by(session, attr, value) -> WebhookDelivery | None
        - list(session, limit, offset) -> Sequence[WebhookDelivery]
        - search(session, statement, limit, offset) -> SearchResult[WebhookDelivery]
        - create(session, instance) -> WebhookDelivery
        - create_many(session, instances) -> Sequence[WebhookDelivery]
        - delete(session, instance) -> None

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with WebhookDelivery model."""
        super().__init__(WebhookDelivery)

    async def find_by_webhook(
        self,
        session: AsyncSession,
        webhook_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult[WebhookDelivery]:
        """Find deliveries for a specific webhook.

        Args:
            session: Database session
            webhook_id: Webhook UUID
            limit: Maximum results
            offset: Results to skip

        Returns:
            SearchResult with deliveries and pagination info
        """
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
        )

        search_result = await self.search(session, stmt, limit=limit, offset=offset)

        self._lazy.debug(
            lambda: f"db.find_by_webhook: webhook_id={webhook_id} -> {len(search_result.items)}/{search_result.total}"
        )
        return search_result

    async def find_by_status(
        self,
        session: AsyncSession,
        status: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WebhookDelivery]:
        """Find deliveries by status.

        Args:
            session: Database session
            status: Delivery status
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of deliveries with the specified status
        """
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.status == status)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.find_by_status: status={status!r} -> {len(items)} items"
        )
        return items

    async def find_retries_due(
        self,
        session: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> Sequence[WebhookDelivery]:
        """Find deliveries that are due for retry.

        Args:
            session: Database session
            as_of: Reference time (defaults to now)

        Returns:
            Sequence of deliveries needing retry
        """
        now = as_of or datetime.utcnow()
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(["pending", "retrying"]),
                WebhookDelivery.next_retry_at.is_not(None),
                WebhookDelivery.next_retry_at <= now,
                WebhookDelivery.attempt_count < WebhookDelivery.max_attempts,
            )
            .order_by(WebhookDelivery.next_retry_at.asc())
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        if items:
            self._logger.info(
                "Found deliveries due for retry",
                extra={
                    "count": len(items),
                    "as_of": now.isoformat(),
                    "operation": "db.find_retries_due",
                },
            )
        else:
            self._lazy.debug(lambda: f"db.find_retries_due: no retries due as of {now}")
        return items

    async def update_status(
        self,
        session: AsyncSession,
        delivery_id: UUID,
        status: str,
        *,
        response_status_code: int | None = None,
        response_body: str | None = None,
        response_time_ms: int | None = None,
        error_message: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> WebhookDelivery | None:
        """Update delivery status and related fields.

        Args:
            session: Database session
            delivery_id: Delivery UUID
            status: New status
            response_status_code: HTTP response status code
            response_body: HTTP response body
            response_time_ms: Response time in milliseconds
            error_message: Error message if failed
            next_retry_at: Next retry time

        Returns:
            Updated delivery or None if not found
        """
        delivery = await self.get(session, delivery_id)
        if delivery is None:
            self._lazy.debug(
                lambda: f"db.update_status({delivery_id}) -> not found"
            )
            return None

        delivery.status = status
        delivery.attempt_count += 1

        if response_status_code is not None:
            delivery.response_status_code = response_status_code
        if response_body is not None:
            # Truncate response body to prevent database bloat
            delivery.response_body = response_body[:5000]
        if response_time_ms is not None:
            delivery.response_time_ms = response_time_ms
        if error_message is not None:
            delivery.error_message = error_message
        if next_retry_at is not None:
            delivery.next_retry_at = next_retry_at

        await session.flush()
        await session.refresh(delivery)

        self._lazy.debug(
            lambda: f"db.update_status({delivery_id}) -> status={status}, attempt={delivery.attempt_count}"
        )
        return delivery


# Factory functions for dependency injection
_webhook_repository: WebhookRepository | None = None
_webhook_delivery_repository: WebhookDeliveryRepository | None = None


def get_webhook_repository() -> WebhookRepository:
    """Get WebhookRepository instance.

    Usage in FastAPI routes:
        from example_service.features.webhooks.repository import (
            WebhookRepository,
            get_webhook_repository,
        )

        @router.get("/{webhook_id}")
        async def get_webhook(
            webhook_id: UUID,
            session: AsyncSession = Depends(get_db_session),
            repo: WebhookRepository = Depends(get_webhook_repository),
        ):
            return await repo.get_or_raise(session, webhook_id)
    """
    global _webhook_repository
    if _webhook_repository is None:
        _webhook_repository = WebhookRepository()
    return _webhook_repository


def get_webhook_delivery_repository() -> WebhookDeliveryRepository:
    """Get WebhookDeliveryRepository instance.

    Usage in FastAPI routes:
        from example_service.features.webhooks.repository import (
            WebhookDeliveryRepository,
            get_webhook_delivery_repository,
        )

        @router.get("/deliveries/{delivery_id}")
        async def get_delivery(
            delivery_id: UUID,
            session: AsyncSession = Depends(get_db_session),
            repo: WebhookDeliveryRepository = Depends(get_webhook_delivery_repository),
        ):
            return await repo.get_or_raise(session, delivery_id)
    """
    global _webhook_delivery_repository
    if _webhook_delivery_repository is None:
        _webhook_delivery_repository = WebhookDeliveryRepository()
    return _webhook_delivery_repository
