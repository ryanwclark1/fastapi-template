"""Query resolvers for webhooks.

Provides read operations for webhooks:
- webhook(id): Get a single webhook by ID
- webhooks(first, after, ...): List webhooks with cursor pagination
- webhookDeliveries(webhookId, first, after): Get deliveries for a webhook
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry
from sqlalchemy import select

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.webhooks import (
    WebhookConnection,
    WebhookDeliveryConnection,
    WebhookDeliveryEdge,
    WebhookDeliveryType,
    WebhookEdge,
    WebhookType,
)
from example_service.features.webhooks.models import Webhook, WebhookDelivery
from example_service.features.webhooks.schemas import WebhookDeliveryRead, WebhookRead

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

FirstArg = Annotated[int, strawberry.argument(description="Number of items to return")]
AfterArg = Annotated[str | None, strawberry.argument(description="Cursor to start after")]


async def webhook_query(info: Info[GraphQLContext, None], id: strawberry.ID) -> WebhookType | None:
    """Get a single webhook by ID."""
    ctx = info.context
    try:
        webhook_uuid = UUID(str(id))
    except ValueError:
        return None

    webhook = await ctx.loaders.webhooks.load(webhook_uuid)
    if webhook is None:
        return None

    webhook_pydantic = WebhookRead.from_orm(webhook)
    return WebhookType.from_pydantic(webhook_pydantic)


async def webhooks_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
) -> WebhookConnection:
    """List webhooks with cursor pagination."""
    ctx = info.context
    from example_service.features.webhooks.repository import get_webhook_repository

    repo = get_webhook_repository()
    stmt = select(Webhook)

    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first,
        after=after,
        order_by=[(Webhook.created_at, "desc"), (Webhook.id, "asc")],
        include_total=True,
    )

    edges = [
        WebhookEdge(
            node=WebhookType.from_pydantic(WebhookRead.from_orm(edge.node)),
            cursor=edge.cursor,
        )
        for edge in connection.edges
    ]

    page_info = PageInfoType(
        has_previous_page=connection.page_info.has_previous_page,
        has_next_page=connection.page_info.has_next_page,
        start_cursor=connection.page_info.start_cursor,
        end_cursor=connection.page_info.end_cursor,
        total_count=connection.page_info.total_count,
    )

    return WebhookConnection(edges=edges, page_info=page_info)


async def webhook_deliveries_query(
    info: Info[GraphQLContext, None],
    webhook_id: strawberry.ID,
    first: FirstArg = 50,
    after: AfterArg = None,
) -> WebhookDeliveryConnection:
    """Get deliveries for a webhook."""
    ctx = info.context
    from example_service.features.webhooks.repository import get_webhook_delivery_repository

    repo = get_webhook_delivery_repository()

    try:
        webhook_uuid = UUID(str(webhook_id))
    except ValueError:
        return WebhookDeliveryConnection(edges=[], page_info=PageInfoType())

    stmt = select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook_uuid)

    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first,
        after=after,
        order_by=[(WebhookDelivery.created_at, "desc"), (WebhookDelivery.id, "asc")],
        include_total=True,
    )

    edges = [
        WebhookDeliveryEdge(
            node=WebhookDeliveryType.from_pydantic(WebhookDeliveryRead.from_orm(edge.node)),
            cursor=edge.cursor,
        )
        for edge in connection.edges
    ]

    page_info = PageInfoType(
        has_previous_page=connection.page_info.has_previous_page,
        has_next_page=connection.page_info.has_next_page,
        start_cursor=connection.page_info.start_cursor,
        end_cursor=connection.page_info.end_cursor,
        total_count=connection.page_info.total_count,
    )

    return WebhookDeliveryConnection(edges=edges, page_info=page_info)


__all__ = ["webhook_deliveries_query", "webhook_query", "webhooks_query"]
