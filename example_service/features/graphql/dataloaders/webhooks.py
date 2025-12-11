"""DataLoaders for batch-loading webhooks and deliveries.

Prevents N+1 queries when resolving webhook and delivery references.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.webhooks.models import Webhook, WebhookDelivery

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class WebhookDataLoader:
    """DataLoader for batch-loading webhooks by ID.

    Prevents N+1 queries when resolving webhook references.

    Usage:
        loader = WebhookDataLoader(session)
        webhook = await loader.load(uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, Webhook | None] = DataLoader(
            load_fn=self._batch_load_webhooks,
        )

    async def _batch_load_webhooks(
        self,
        ids: list[UUID],
    ) -> list[Webhook | None]:
        """Batch load webhooks by IDs.

        Args:
            ids: List of webhook UUIDs to load

        Returns:
            List of Webhook objects (or None) in same order as ids
        """
        if not ids:
            return []

        stmt = select(Webhook).where(Webhook.id.in_(ids))
        result = await self._session.execute(stmt)
        webhooks = {w.id: w for w in result.scalars().all()}

        return [webhooks.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> Webhook | None:
        """Load a single webhook by ID.

        Args:
            id_: Webhook UUID

        Returns:
            Webhook if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[Webhook | None]:
        """Load multiple webhooks by IDs.

        Args:
            ids: List of webhook UUIDs

        Returns:
            List of Webhook objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class WebhookDeliveryDataLoader:
    """DataLoader for batch-loading webhook deliveries by ID.

    Prevents N+1 queries when resolving delivery references.

    Usage:
        loader = WebhookDeliveryDataLoader(session)
        delivery = await loader.load(uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, WebhookDelivery | None] = DataLoader(
            load_fn=self._batch_load_deliveries,
        )

    async def _batch_load_deliveries(
        self,
        ids: list[UUID],
    ) -> list[WebhookDelivery | None]:
        """Batch load webhook deliveries by IDs.

        Args:
            ids: List of delivery UUIDs to load

        Returns:
            List of WebhookDelivery objects (or None) in same order as ids
        """
        if not ids:
            return []

        stmt = select(WebhookDelivery).where(WebhookDelivery.id.in_(ids))
        result = await self._session.execute(stmt)
        deliveries = {d.id: d for d in result.scalars().all()}

        return [deliveries.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> WebhookDelivery | None:
        """Load a single webhook delivery by ID.

        Args:
            id_: Delivery UUID

        Returns:
            WebhookDelivery if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[WebhookDelivery | None]:
        """Load multiple deliveries by IDs.

        Args:
            ids: List of delivery UUIDs

        Returns:
            List of WebhookDelivery objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class WebhookDeliveriesByWebhookDataLoader:
    """DataLoader for batch-loading deliveries by webhook ID.

    Solves N+1 problem when loading deliveries for multiple webhooks.
    Maps webhook_id -> list of deliveries.

    Usage:
        loader = WebhookDeliveriesByWebhookDataLoader(session)
        deliveries = await loader.load(webhook_uuid)  # Returns list[WebhookDelivery]
    """

    def __init__(self, session: AsyncSession, limit: int = 100) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
            limit: Maximum number of deliveries to return per webhook (default: 100)
        """
        self._session = session
        self._limit = limit
        self._loader: DataLoader[UUID, list[WebhookDelivery]] = DataLoader(
            load_fn=self._batch_load_deliveries_by_webhook,
        )

    async def _batch_load_deliveries_by_webhook(
        self,
        webhook_ids: list[UUID],
    ) -> list[list[WebhookDelivery]]:
        """Batch load deliveries for multiple webhooks.

        Returns most recent deliveries up to limit per webhook.

        Args:
            webhook_ids: List of webhook UUIDs

        Returns:
            List of delivery lists, one per webhook_id (empty list if none)
        """
        if not webhook_ids:
            return []

        # Single query for all deliveries, ordered by creation time
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id.in_(webhook_ids))
            .order_by(WebhookDelivery.created_at.desc())
        )
        result = await self._session.execute(stmt)
        all_deliveries = result.scalars().all()

        # Group by webhook_id, limit per webhook
        deliveries_by_webhook: dict[UUID, list[WebhookDelivery]] = {wid: [] for wid in webhook_ids}
        for delivery in all_deliveries:
            webhook_deliveries = deliveries_by_webhook.setdefault(delivery.webhook_id, [])
            if len(webhook_deliveries) < self._limit:
                webhook_deliveries.append(delivery)

        # Return in same order as requested
        return [deliveries_by_webhook.get(wid, []) for wid in webhook_ids]

    async def load(self, webhook_id: UUID) -> list[WebhookDelivery]:
        """Load deliveries for a single webhook.

        Args:
            webhook_id: Webhook UUID

        Returns:
            List of deliveries for the webhook (empty list if none, max limit)
        """
        return await self._loader.load(webhook_id)

    async def load_many(self, webhook_ids: list[UUID]) -> list[list[WebhookDelivery]]:
        """Load deliveries for multiple webhooks.

        Args:
            webhook_ids: List of webhook UUIDs

        Returns:
            List of delivery lists, one per webhook_id
        """
        return await self._loader.load_many(webhook_ids)


__all__ = [
    "WebhookDataLoader",
    "WebhookDeliveriesByWebhookDataLoader",
    "WebhookDeliveryDataLoader",
]
