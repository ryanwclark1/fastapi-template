"""Webhook management CLI commands.

This module provides CLI commands for managing webhooks:
- List and create webhooks
- View webhook deliveries
- Test and retry deliveries
- Manage webhook secrets
"""

import sys
from uuid import UUID

import click

from example_service.cli.utils import (
    coro,
    error,
    header,
    info,
    section,
    success,
    warning,
)


@click.group(name="webhooks")
def webhooks() -> None:
    """Webhook management commands.

    Commands for managing webhook endpoints, delivery history,
    and testing webhook functionality.
    """


@webhooks.command(name="list")
@click.option(
    "--active/--inactive",
    default=None,
    help="Filter by active status",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    help="Maximum webhooks to display (default: 50)",
)
@click.option(
    "--offset",
    default=0,
    type=int,
    help="Number of webhooks to skip",
)
@coro
async def list_webhooks(active: bool | None, limit: int, offset: int) -> None:
    """List all registered webhooks.

    Shows webhook name, URL, event types, and status.
    """
    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    header("Registered Webhooks")

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhooks_list, total = await service.list_webhooks(
            is_active=active,
            limit=limit,
            offset=offset,
        )

        if not webhooks_list:
            info("No webhooks found")
            return

        click.echo()
        for webhook in webhooks_list:
            status = click.style("Active", fg="green") if webhook.is_active else click.style("Inactive", fg="red")
            click.echo(f"  ID: {webhook.id}")
            click.echo(f"    Name: {webhook.name}")
            click.echo(f"    URL: {webhook.url}")
            click.echo(f"    Status: {status}")
            click.echo(f"    Events: {', '.join(webhook.event_types)}")
            click.echo(f"    Max Retries: {webhook.max_retries}")
            click.echo(f"    Timeout: {webhook.timeout_seconds}s")
            click.echo(f"    Created: {webhook.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo()

        success(f"Showing {len(webhooks_list)}/{total} webhooks")


@webhooks.command(name="show")
@click.argument("webhook_id")
@click.option(
    "--show-secret",
    is_flag=True,
    help="Show the webhook secret",
)
@coro
async def show_webhook(webhook_id: str, show_secret: bool) -> None:
    """Show details of a specific webhook.

    WEBHOOK_ID is the UUID of the webhook.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhook = await service.get_webhook(webhook_uuid)

        if not webhook:
            error(f"Webhook not found: {webhook_id}")
            sys.exit(1)

        header(f"Webhook: {webhook.name}")

        section("Configuration")
        click.echo(f"  ID: {webhook.id}")
        click.echo(f"  URL: {webhook.url}")
        status = click.style("Active", fg="green") if webhook.is_active else click.style("Inactive", fg="red")
        click.echo(f"  Status: {status}")
        click.echo(f"  Event Types: {', '.join(webhook.event_types)}")
        click.echo(f"  Max Retries: {webhook.max_retries}")
        click.echo(f"  Timeout: {webhook.timeout_seconds}s")

        if show_secret:
            section("Secret")
            click.echo(f"  {webhook.secret}")
        else:
            info("Use --show-secret to display the webhook secret")

        if webhook.custom_headers:
            section("Custom Headers")
            for key, value in webhook.custom_headers.items():
                click.echo(f"  {key}: {value}")

        if webhook.description:
            section("Description")
            click.echo(f"  {webhook.description}")

        section("Timestamps")
        click.echo(f"  Created: {webhook.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"  Updated: {webhook.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

        success("Webhook details retrieved")


@webhooks.command(name="create")
@click.option("--name", "-n", required=True, help="Webhook name")
@click.option("--url", "-u", required=True, help="Webhook URL")
@click.option(
    "--event",
    "-e",
    "event_types",
    multiple=True,
    required=True,
    help="Event types to subscribe to (can specify multiple)",
)
@click.option("--description", "-d", help="Webhook description")
@click.option("--max-retries", default=5, type=int, help="Max retry attempts (default: 5)")
@click.option("--timeout", default=30, type=int, help="Request timeout in seconds (default: 30)")
@click.option("--inactive", is_flag=True, help="Create webhook as inactive")
@coro
async def create_webhook(
    name: str,
    url: str,
    event_types: tuple[str, ...],
    description: str | None,
    max_retries: int,
    timeout: int,
    inactive: bool,
) -> None:
    """Create a new webhook.

    Examples:
    \b
      example-service webhooks create -n "Order Events" -u "https://example.com/webhook" -e order.created -e order.updated
    """
    from example_service.features.webhooks.schemas import WebhookCreate
    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    header("Creating Webhook")

    async with async_sessionmaker() as session:
        service = WebhookService(session)

        try:
            payload = WebhookCreate(
                name=name,
                url=url,  # type: ignore[arg-type]
                event_types=list(event_types),
                description=description,
                max_retries=max_retries,
                timeout_seconds=timeout,
                is_active=not inactive,
            )

            webhook = await service.create_webhook(payload)
            await session.commit()

            success(f"Webhook created: {webhook.id}")
            click.echo(f"\n  Name: {webhook.name}")
            click.echo(f"  URL: {webhook.url}")
            click.echo(f"  Events: {', '.join(webhook.event_types)}")
            click.echo(f"\n  Secret: {webhook.secret}")
            warning("\nStore this secret securely - it cannot be retrieved later!")

        except ValueError as e:
            error(f"Validation error: {e}")
            sys.exit(1)


@webhooks.command(name="delete")
@click.argument("webhook_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
@coro
async def delete_webhook(webhook_id: str, force: bool) -> None:
    """Delete a webhook.

    WEBHOOK_ID is the UUID of the webhook to delete.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhook = await service.get_webhook(webhook_uuid)

        if not webhook:
            error(f"Webhook not found: {webhook_id}")
            sys.exit(1)

        if not force:
            if not click.confirm(f"Delete webhook '{webhook.name}'?"):
                info("Deletion cancelled")
                return

        deleted = await service.delete_webhook(webhook_uuid)
        await session.commit()

        if deleted:
            success(f"Webhook deleted: {webhook_id}")
        else:
            error("Failed to delete webhook")
            sys.exit(1)


@webhooks.command(name="activate")
@click.argument("webhook_id")
@coro
async def activate_webhook(webhook_id: str) -> None:
    """Activate a webhook.

    WEBHOOK_ID is the UUID of the webhook to activate.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.schemas import WebhookUpdate
    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhook = await service.update_webhook(
            webhook_uuid,
            WebhookUpdate(is_active=True),
        )
        await session.commit()

        if webhook:
            success(f"Webhook activated: {webhook.name}")
        else:
            error(f"Webhook not found: {webhook_id}")
            sys.exit(1)


@webhooks.command(name="deactivate")
@click.argument("webhook_id")
@coro
async def deactivate_webhook(webhook_id: str) -> None:
    """Deactivate a webhook.

    WEBHOOK_ID is the UUID of the webhook to deactivate.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.schemas import WebhookUpdate
    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhook = await service.update_webhook(
            webhook_uuid,
            WebhookUpdate(is_active=False),
        )
        await session.commit()

        if webhook:
            success(f"Webhook deactivated: {webhook.name}")
        else:
            error(f"Webhook not found: {webhook_id}")
            sys.exit(1)


@webhooks.command(name="regenerate-secret")
@click.argument("webhook_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
@coro
async def regenerate_secret(webhook_id: str, force: bool) -> None:
    """Regenerate the secret for a webhook.

    WEBHOOK_ID is the UUID of the webhook.
    This will invalidate the existing secret immediately.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    if not force:
        warning("This will invalidate the current secret immediately!")
        if not click.confirm("Continue?"):
            info("Cancelled")
            return

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        webhook = await service.regenerate_secret(webhook_uuid)
        await session.commit()

        if webhook:
            success("Secret regenerated")
            click.echo(f"\n  New Secret: {webhook.secret}")
            warning("\nStore this secret securely - it cannot be retrieved later!")
        else:
            error(f"Webhook not found: {webhook_id}")
            sys.exit(1)


@webhooks.command(name="deliveries")
@click.argument("webhook_id")
@click.option(
    "--limit",
    default=20,
    type=int,
    help="Maximum deliveries to display (default: 20)",
)
@coro
async def list_deliveries(webhook_id: str, limit: int) -> None:
    """List delivery history for a webhook.

    WEBHOOK_ID is the UUID of the webhook.
    """
    try:
        webhook_uuid = UUID(webhook_id)
    except ValueError:
        error(f"Invalid webhook ID format: {webhook_id}")
        sys.exit(1)

    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    header(f"Deliveries for Webhook: {webhook_id}")

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        deliveries, total = await service.list_deliveries(
            webhook_uuid,
            limit=limit,
        )

        if not deliveries:
            info("No deliveries found")
            return

        click.echo()
        for delivery in deliveries:
            status_color = {
                "pending": "yellow",
                "delivered": "green",
                "failed": "red",
                "retrying": "blue",
            }.get(delivery.status, "white")

            click.echo(f"  ID: {delivery.id}")
            click.echo(f"    Event: {delivery.event_type} ({delivery.event_id})")
            click.secho(f"    Status: {delivery.status}", fg=status_color)
            click.echo(f"    Attempts: {delivery.attempt_count}/{delivery.max_attempts}")
            if delivery.response_status_code:
                click.echo(f"    Response Code: {delivery.response_status_code}")
            if delivery.response_time_ms:
                click.echo(f"    Response Time: {delivery.response_time_ms}ms")
            if delivery.error_message:
                click.secho(f"    Error: {delivery.error_message}", fg="red")
            if delivery.next_retry_at:
                click.echo(f"    Next Retry: {delivery.next_retry_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"    Created: {delivery.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo()

        success(f"Showing {len(deliveries)}/{total} deliveries")


@webhooks.command(name="retry")
@click.argument("delivery_id")
@coro
async def retry_delivery(delivery_id: str) -> None:
    """Retry a failed webhook delivery.

    DELIVERY_ID is the UUID of the delivery to retry.
    """
    try:
        delivery_uuid = UUID(delivery_id)
    except ValueError:
        error(f"Invalid delivery ID format: {delivery_id}")
        sys.exit(1)

    from example_service.features.webhooks.service import WebhookService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = WebhookService(session)
        delivery = await service.retry_delivery(delivery_uuid)
        await session.commit()

        if delivery:
            success(f"Delivery queued for retry: {delivery_id}")
        else:
            error(f"Delivery not found: {delivery_id}")
            sys.exit(1)


@webhooks.command(name="stats")
@coro
async def webhook_stats() -> None:
    """Show webhook statistics.

    Displays overall webhook and delivery statistics.
    """
    from sqlalchemy import func, select

    from example_service.features.webhooks.models import Webhook, WebhookDelivery
    from example_service.infra.database.session import async_sessionmaker

    header("Webhook Statistics")

    async with async_sessionmaker() as session:
        # Webhook counts
        webhook_count = await session.execute(select(func.count(Webhook.id)))
        total_webhooks = webhook_count.scalar() or 0

        active_count = await session.execute(
            select(func.count(Webhook.id)).where(Webhook.is_active == True)  # noqa: E712
        )
        active_webhooks = active_count.scalar() or 0

        section("Webhooks")
        click.echo(f"  Total: {total_webhooks}")
        click.echo(f"  Active: {active_webhooks}")
        click.echo(f"  Inactive: {total_webhooks - active_webhooks}")

        # Delivery stats
        delivery_count = await session.execute(select(func.count(WebhookDelivery.id)))
        total_deliveries = delivery_count.scalar() or 0

        status_counts = await session.execute(
            select(WebhookDelivery.status, func.count(WebhookDelivery.id))
            .group_by(WebhookDelivery.status)
        )
        status_dict = {row[0]: row[1] for row in status_counts.all()}

        section("Deliveries")
        click.echo(f"  Total: {total_deliveries}")
        for status, count in status_dict.items():
            status_color = {
                "pending": "yellow",
                "delivered": "green",
                "failed": "red",
                "retrying": "blue",
            }.get(status, "white")
            click.secho(f"  {status.capitalize()}: {count}", fg=status_color)

        if total_deliveries > 0:
            delivered = status_dict.get("delivered", 0)
            success_rate = (delivered / total_deliveries) * 100
            click.echo(f"\n  Success Rate: {success_rate:.1f}%")

        success("Stats retrieved")
