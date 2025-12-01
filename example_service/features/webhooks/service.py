"""Service layer for webhook-specific business logic."""

from __future__ import annotations

import ipaddress
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from example_service.core.services.base import BaseService
from example_service.features.webhooks.models import Webhook, WebhookDelivery
from example_service.features.webhooks.repository import (
    WebhookDeliveryRepository,
    WebhookRepository,
    get_webhook_delivery_repository,
    get_webhook_repository,
)
from example_service.features.webhooks.schemas import (
    DeliveryStatus,
    WebhookCreate,
    WebhookUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class WebhookService(BaseService):
    """Orchestrates webhook operations using repositories."""

    def __init__(
        self,
        session: AsyncSession,
        webhook_repository: WebhookRepository | None = None,
        delivery_repository: WebhookDeliveryRepository | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._webhook_repo = webhook_repository or get_webhook_repository()
        self._delivery_repo = delivery_repository or get_webhook_delivery_repository()

    def validate_url(self, url: str) -> None:
        """Validate webhook URL and block internal/private IPs.

        Args:
            url: URL to validate

        Raises:
            ValueError: If URL points to internal/private network
        """
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            raise ValueError("Invalid URL: missing hostname")

        # Try to resolve hostname to IP
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            # Hostname is a domain name, not an IP
            # For production, you might want to resolve DNS and check the resolved IPs
            # For now, we'll allow domain names
            return

        # Block private/internal IP ranges
        if ip.is_private:
            raise ValueError(
                f"Webhook URL cannot point to private IP address: {hostname}"
            )

        if ip.is_loopback:
            raise ValueError(
                f"Webhook URL cannot point to loopback address: {hostname}"
            )

        if ip.is_reserved:
            raise ValueError(
                f"Webhook URL cannot point to reserved IP address: {hostname}"
            )

        if ip.is_link_local:
            raise ValueError(
                f"Webhook URL cannot point to link-local address: {hostname}"
            )

    def generate_secret(self) -> str:
        """Generate a secure HMAC secret.

        Returns:
            URL-safe base64-encoded secret
        """
        return secrets.token_urlsafe(32)

    async def create_webhook(self, payload: WebhookCreate) -> Webhook:
        """Create and persist a new webhook.

        Args:
            payload: Webhook creation payload

        Returns:
            Created webhook

        Raises:
            ValueError: If URL validation fails
        """
        # Validate URL
        self.validate_url(str(payload.url))

        # Generate HMAC secret
        secret = self.generate_secret()

        # Create webhook instance
        webhook = Webhook(
            name=payload.name,
            description=payload.description,
            url=str(payload.url),
            secret=secret,
            event_types=payload.event_types,
            is_active=payload.is_active,
            max_retries=payload.max_retries,
            timeout_seconds=payload.timeout_seconds,
            custom_headers=payload.custom_headers,
        )

        created = await self._webhook_repo.create(self._session, webhook)

        # INFO level - business event (audit trail)
        self.logger.info(
            "Webhook created",
            extra={
                "webhook_id": str(created.id),
                "name": payload.name,
                "event_types": payload.event_types,
                "operation": "service.create_webhook",
            },
        )
        return created

    async def get_webhook(self, webhook_id: UUID) -> Webhook | None:
        """Fetch a webhook by id.

        Args:
            webhook_id: Webhook UUID

        Returns:
            Webhook or None if not found
        """
        webhook = await self._webhook_repo.get(self._session, webhook_id)

        self._lazy.debug(
            lambda: f"service.get_webhook({webhook_id}) -> {'found' if webhook else 'not found'}"
        )
        return webhook

    async def list_webhooks(
        self,
        *,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Webhook], int]:
        """List webhooks with filtering and pagination.

        Args:
            is_active: Filter by active status
            limit: Maximum results
            offset: Results to skip

        Returns:
            Tuple of (webhooks list, total count)
        """
        search_result = await self._webhook_repo.search_webhooks(
            self._session,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        self._lazy.debug(
            lambda: f"service.list_webhooks(is_active={is_active}, limit={limit}, offset={offset}) -> {len(search_result.items)}/{search_result.total}"
        )
        return list(search_result.items), search_result.total

    async def update_webhook(
        self,
        webhook_id: UUID,
        payload: WebhookUpdate,
    ) -> Webhook | None:
        """Update an existing webhook.

        Args:
            webhook_id: Webhook UUID
            payload: Update payload

        Returns:
            Updated webhook or None if not found

        Raises:
            ValueError: If URL validation fails
        """
        webhook = await self._webhook_repo.get(self._session, webhook_id)
        if webhook is None:
            self._lazy.debug(
                lambda: f"service.update_webhook({webhook_id}) -> not found"
            )
            return None

        # Validate URL if provided
        if payload.url is not None:
            self.validate_url(str(payload.url))
            webhook.url = str(payload.url)

        # Update fields
        if payload.name is not None:
            webhook.name = payload.name
        if payload.description is not None:
            webhook.description = payload.description
        if payload.event_types is not None:
            webhook.event_types = payload.event_types
        if payload.is_active is not None:
            webhook.is_active = payload.is_active
        if payload.max_retries is not None:
            webhook.max_retries = payload.max_retries
        if payload.timeout_seconds is not None:
            webhook.timeout_seconds = payload.timeout_seconds
        if payload.custom_headers is not None:
            webhook.custom_headers = payload.custom_headers

        await self._session.flush()
        await self._session.refresh(webhook)

        # INFO level - state change (business event)
        self.logger.info(
            "Webhook updated",
            extra={"webhook_id": str(webhook_id), "operation": "service.update_webhook"},
        )
        return webhook

    async def delete_webhook(self, webhook_id: UUID) -> bool:
        """Delete a webhook.

        Args:
            webhook_id: Webhook UUID

        Returns:
            True if deleted, False if not found
        """
        webhook = await self._webhook_repo.get(self._session, webhook_id)
        if webhook is None:
            self._lazy.debug(
                lambda: f"service.delete_webhook({webhook_id}) -> not found"
            )
            return False

        await self._webhook_repo.delete(self._session, webhook)

        # INFO level - permanent data removal (audit trail)
        self.logger.info(
            "Webhook deleted",
            extra={"webhook_id": str(webhook_id), "operation": "service.delete_webhook"},
        )
        return True

    async def regenerate_secret(self, webhook_id: UUID) -> Webhook | None:
        """Regenerate HMAC secret for a webhook.

        Args:
            webhook_id: Webhook UUID

        Returns:
            Updated webhook or None if not found
        """
        webhook = await self._webhook_repo.get(self._session, webhook_id)
        if webhook is None:
            self._lazy.debug(
                lambda: f"service.regenerate_secret({webhook_id}) -> not found"
            )
            return None

        # Generate new secret
        webhook.secret = self.generate_secret()

        await self._session.flush()
        await self._session.refresh(webhook)

        # INFO level - security event (secret rotation)
        self.logger.info(
            "Webhook secret regenerated",
            extra={"webhook_id": str(webhook_id), "operation": "service.regenerate_secret"},
        )
        return webhook

    async def list_deliveries(
        self,
        webhook_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[WebhookDelivery], int]:
        """List delivery history for a webhook.

        Args:
            webhook_id: Webhook UUID
            limit: Maximum results
            offset: Results to skip

        Returns:
            Tuple of (deliveries list, total count)
        """
        search_result = await self._delivery_repo.find_by_webhook(
            self._session,
            webhook_id,
            limit=limit,
            offset=offset,
        )

        self._lazy.debug(
            lambda: f"service.list_deliveries({webhook_id}, limit={limit}, offset={offset}) -> {len(search_result.items)}/{search_result.total}"
        )
        return list(search_result.items), search_result.total

    async def get_delivery(self, delivery_id: UUID) -> WebhookDelivery | None:
        """Get a specific delivery record.

        Args:
            delivery_id: Delivery UUID

        Returns:
            Delivery or None if not found
        """
        delivery = await self._delivery_repo.get(self._session, delivery_id)

        self._lazy.debug(
            lambda: f"service.get_delivery({delivery_id}) -> {'found' if delivery else 'not found'}"
        )
        return delivery

    async def retry_delivery(self, delivery_id: UUID) -> WebhookDelivery | None:
        """Manually retry a failed delivery.

        Args:
            delivery_id: Delivery UUID

        Returns:
            Updated delivery or None if not found
        """
        delivery = await self._delivery_repo.get(self._session, delivery_id)
        if delivery is None:
            self._lazy.debug(
                lambda: f"service.retry_delivery({delivery_id}) -> not found"
            )
            return None

        # Reset status to allow retry
        delivery.status = DeliveryStatus.PENDING.value
        delivery.next_retry_at = None

        await self._session.flush()
        await self._session.refresh(delivery)

        # INFO level - manual intervention (audit trail)
        self.logger.info(
            "Delivery retry requested",
            extra={"delivery_id": str(delivery_id), "operation": "service.retry_delivery"},
        )
        return delivery


__all__ = ["WebhookService"]
