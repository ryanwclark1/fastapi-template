"""Audit log management CLI commands.

This module provides CLI commands for viewing and managing audit logs:
- Query audit logs with filters
- View entity history
- Generate audit summaries
- Export audit reports
"""

from datetime import datetime, timedelta
import sys

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


@click.group(name="audit")
def audit() -> None:
    """Audit log management commands.

    Commands for querying audit logs, viewing entity history,
    and generating compliance reports.
    """


@audit.command(name="list")
@click.option(
    "--tenant-id",
    "-t",
    help="Filter by tenant ID",
)
@click.option(
    "--user-id",
    "-u",
    help="Filter by user ID",
)
@click.option(
    "--entity-type",
    "-e",
    help="Filter by entity type (e.g., user, reminder, webhook)",
)
@click.option(
    "--action",
    "-a",
    help="Filter by action type (e.g., create, update, delete)",
)
@click.option(
    "--days",
    default=7,
    type=int,
    help="Number of days to show (default: 7)",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    help="Maximum entries to display (default: 50)",
)
@click.option(
    "--failures-only",
    is_flag=True,
    help="Show only failed actions",
)
@coro
async def list_logs(
    tenant_id: str | None,
    user_id: str | None,
    entity_type: str | None,
    action: str | None,
    days: int,
    limit: int,
    failures_only: bool,
) -> None:
    """List audit log entries with optional filters.

    Examples:
    \b
      example-service audit list --entity-type user --days 30
      example-service audit list --user-id user-123 --failures-only
      example-service audit list --action delete --limit 100
    """
    from datetime import UTC

    from example_service.features.audit.schemas import AuditLogQuery
    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header("Audit Log Entries")
    info(f"Period: Last {days} days")

    start_time = datetime.now(UTC) - timedelta(days=days)

    async with async_sessionmaker() as session:
        service = AuditService(session)

        query = AuditLogQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            start_time=start_time,
            limit=limit,
            success=False if failures_only else None,
        )

        # Handle action filter manually since it might not match enum
        response = await service.query(query)

        # Filter by action string if provided
        if action:
            response.items = [
                item for item in response.items
                if item.action.lower() == action.lower()
            ]

        if not response.items:
            info("No audit entries found matching criteria")
            return

        click.echo()
        for entry in response.items:
            status_color = "green" if entry.success else "red"
            status_icon = "+" if entry.success else "x"

            click.echo(f"  [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]")
            click.secho(f"    [{status_icon}] {entry.action}", fg=status_color)
            click.echo(f"    Entity: {entry.entity_type}", nl=False)
            if entry.entity_id:
                click.echo(f" ({entry.entity_id})")
            else:
                click.echo()
            if entry.user_id:
                click.echo(f"    User: {entry.user_id}")
            if entry.ip_address:
                click.echo(f"    IP: {entry.ip_address}")
            if entry.endpoint:
                click.echo(f"    Endpoint: {entry.method or ''} {entry.endpoint}")
            if entry.duration_ms:
                click.echo(f"    Duration: {entry.duration_ms}ms")
            if entry.error_message:
                click.secho(f"    Error: {entry.error_message}", fg="red")
            click.echo()

        success(f"Showing {len(response.items)}/{response.total} entries")
        if response.has_more:
            info("Use --limit to show more entries")


@audit.command(name="show")
@click.argument("audit_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@coro
async def show_entry(audit_id: str, output_format: str) -> None:
    """Show details of a specific audit log entry.

    AUDIT_ID is the UUID of the audit log entry.
    """
    from uuid import UUID

    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    try:
        entry_uuid = UUID(audit_id)
    except ValueError:
        error(f"Invalid audit ID format: {audit_id}")
        sys.exit(1)

    async with async_sessionmaker() as session:
        service = AuditService(session)
        entry = await service.get_by_id(entry_uuid)

        if not entry:
            error(f"Audit entry not found: {audit_id}")
            sys.exit(1)

        if output_format == "json":
            import json

            from example_service.features.audit.schemas import AuditLogResponse

            response = AuditLogResponse.model_validate(entry)
            click.echo(json.dumps(response.model_dump(mode="json"), indent=2, default=str))
        else:
            header(f"Audit Entry: {audit_id}")

            section("Basic Information")
            click.echo(f"  Timestamp: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"  Action: {entry.action}")
            click.echo(f"  Entity Type: {entry.entity_type}")
            if entry.entity_id:
                click.echo(f"  Entity ID: {entry.entity_id}")
            status = click.style("Success", fg="green") if entry.success else click.style("Failed", fg="red")
            click.echo(f"  Status: {status}")

            section("Actor Information")
            if entry.user_id:
                click.echo(f"  User ID: {entry.user_id}")
            if entry.actor_roles:
                click.echo(f"  Roles: {', '.join(entry.actor_roles)}")
            if entry.tenant_id:
                click.echo(f"  Tenant ID: {entry.tenant_id}")

            section("Request Context")
            if entry.ip_address:
                click.echo(f"  IP Address: {entry.ip_address}")
            if entry.user_agent:
                click.echo(f"  User Agent: {entry.user_agent[:60]}...")
            if entry.endpoint:
                click.echo(f"  Endpoint: {entry.method or ''} {entry.endpoint}")
            if entry.request_id:
                click.echo(f"  Request ID: {entry.request_id}")
            if entry.duration_ms:
                click.echo(f"  Duration: {entry.duration_ms}ms")

            if entry.old_values or entry.new_values:
                section("Data Changes")
                if entry.old_values:
                    click.echo("  Old Values:")
                    for key, value in entry.old_values.items():
                        click.echo(f"    {key}: {value}")
                if entry.new_values:
                    click.echo("  New Values:")
                    for key, value in entry.new_values.items():
                        click.echo(f"    {key}: {value}")
                if entry.changes:
                    click.echo("  Changed Fields:")
                    for key, change in entry.changes.items():
                        click.echo(f"    {key}: {change.get('old')} -> {change.get('new')}")

            if entry.error_message:
                section("Error")
                click.secho(f"  {entry.error_message}", fg="red")

            if entry.context_data:
                section("Additional Context")
                for key, value in entry.context_data.items():
                    click.echo(f"  {key}: {value}")

            success("Entry retrieved")


@audit.command(name="history")
@click.argument("entity_type")
@click.argument("entity_id")
@click.option(
    "--limit",
    default=100,
    type=int,
    help="Maximum entries to show (default: 100)",
)
@coro
async def entity_history(entity_type: str, entity_id: str, limit: int) -> None:
    """Show audit history for a specific entity.

    ENTITY_TYPE is the type of entity (e.g., user, reminder, webhook).
    ENTITY_ID is the ID of the entity.

    Examples:
    \b
      example-service audit history user user-123
      example-service audit history reminder abc-456
    """
    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header(f"Audit History: {entity_type}/{entity_id}")

    async with async_sessionmaker() as session:
        service = AuditService(session)
        history = await service.get_entity_history(entity_type, entity_id, limit=limit)

        if not history.entries:
            info("No audit history found for this entity")
            return

        section("Entity Lifecycle")
        if history.created_at:
            click.echo(f"  Created: {history.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if history.created_by:
                click.echo(f"    By: {history.created_by}")
        if history.last_modified_at:
            click.echo(f"  Last Modified: {history.last_modified_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if history.last_modified_by:
                click.echo(f"    By: {history.last_modified_by}")
        click.echo(f"  Total Changes: {history.total_changes}")

        section("Change History")
        for entry in history.entries:
            status_icon = "+" if entry.success else "x"
            status_color = "green" if entry.success else "red"

            click.echo(f"\n  [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]")
            click.secho(f"    [{status_icon}] {entry.action}", fg=status_color)
            if entry.user_id:
                click.echo(f"    User: {entry.user_id}")
            if entry.changes:
                click.echo("    Changes:")
                for field, change in entry.changes.items():
                    click.echo(f"      {field}: {change.get('old')} -> {change.get('new')}")

        success(f"Showing {len(history.entries)} entries")


@audit.command(name="summary")
@click.option(
    "--tenant-id",
    "-t",
    help="Filter by tenant ID",
)
@click.option(
    "--days",
    default=30,
    type=int,
    help="Number of days to analyze (default: 30)",
)
@coro
async def show_summary(tenant_id: str | None, days: int) -> None:
    """Show audit log summary statistics.

    Displays counts by action type, entity type, and success rate.
    """
    from datetime import UTC

    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header("Audit Summary")
    info(f"Period: Last {days} days")

    start_time = datetime.now(UTC) - timedelta(days=days)
    end_time = datetime.now(UTC)

    async with async_sessionmaker() as session:
        service = AuditService(session)
        summary = await service.get_summary(
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
        )

        section("Overview")
        click.echo(f"  Total Entries: {summary.total_entries:,}")
        click.echo(f"  Unique Users: {summary.unique_users}")
        click.echo(f"  Success Rate: {summary.success_rate:.1f}%")
        if summary.dangerous_actions_count > 0:
            click.secho(f"  Dangerous Actions: {summary.dangerous_actions_count}", fg="yellow")

        if summary.time_range_start and summary.time_range_end:
            click.echo(f"  Time Range: {summary.time_range_start.strftime('%Y-%m-%d')} to {summary.time_range_end.strftime('%Y-%m-%d')}")

        if summary.actions_count:
            section("By Action Type")
            sorted_actions = sorted(summary.actions_count.items(), key=lambda x: x[1], reverse=True)
            for action, count in sorted_actions[:15]:
                pct = (count / summary.total_entries * 100) if summary.total_entries else 0
                click.echo(f"  {action}: {count:,} ({pct:.1f}%)")

        if summary.entity_types_count:
            section("By Entity Type")
            sorted_entities = sorted(summary.entity_types_count.items(), key=lambda x: x[1], reverse=True)
            for entity_type, count in sorted_entities[:10]:
                pct = (count / summary.total_entries * 100) if summary.total_entries else 0
                click.echo(f"  {entity_type}: {count:,} ({pct:.1f}%)")

        success("Summary complete")


@audit.command(name="dangerous")
@click.option(
    "--tenant-id",
    "-t",
    help="Filter by tenant ID",
)
@click.option(
    "--days",
    default=7,
    type=int,
    help="Number of days to show (default: 7)",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    help="Maximum entries to display (default: 50)",
)
@coro
async def list_dangerous(tenant_id: str | None, days: int, limit: int) -> None:
    """List dangerous actions for security review.

    Shows deletes, revokes, suspensions, and other high-impact actions.
    """
    from datetime import UTC

    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header("Dangerous Actions Review")
    info(f"Period: Last {days} days")

    start_time = datetime.now(UTC) - timedelta(days=days)
    end_time = datetime.now(UTC)

    async with async_sessionmaker() as session:
        service = AuditService(session)
        response = await service.list_dangerous_actions(
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        if not response.items:
            success("No dangerous actions found in this period")
            return

        warning(f"Found {response.total} dangerous actions")
        click.echo()

        for entry in response.items:
            click.echo(f"  [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]")
            click.secho(f"    Action: {entry.action}", fg="red")
            click.echo(f"    Entity: {entry.entity_type}", nl=False)
            if entry.entity_id:
                click.echo(f" ({entry.entity_id})")
            else:
                click.echo()
            if entry.user_id:
                click.echo(f"    User: {entry.user_id}")
            if entry.ip_address:
                click.echo(f"    IP: {entry.ip_address}")
            click.echo()

        if response.has_more:
            info(f"Use --limit to show more (total: {response.total})")


@audit.command(name="export")
@click.option(
    "--tenant-id",
    "-t",
    help="Filter by tenant ID",
)
@click.option(
    "--days",
    default=30,
    type=int,
    help="Number of days to export (default: 30)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file path (default: stdout)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv"]),
    default="json",
    help="Output format (default: json)",
)
@coro
async def export_logs(
    tenant_id: str | None,
    days: int,
    output: str | None,
    output_format: str,
) -> None:
    """Export audit logs to file.

    Creates a compliance-ready export of audit logs.
    """
    from datetime import UTC

    from example_service.features.audit.schemas import AuditLogQuery
    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header("Exporting Audit Logs")
    info(f"Period: Last {days} days")

    start_time = datetime.now(UTC) - timedelta(days=days)

    async with async_sessionmaker() as session:
        service = AuditService(session)

        query = AuditLogQuery(
            tenant_id=tenant_id,
            start_time=start_time,
            limit=10000,  # Large limit for export
        )

        response = await service.query(query)

        if not response.items:
            info("No entries to export")
            return

        info(f"Exporting {len(response.items)} entries...")

        if output_format == "json":
            import json

            data = [item.model_dump(mode="json") for item in response.items]
            content = json.dumps(data, indent=2, default=str)
        else:  # csv
            import csv
            import io

            buffer = io.StringIO()
            fieldnames = [
                "timestamp", "action", "entity_type", "entity_id",
                "user_id", "tenant_id", "success", "ip_address",
                "endpoint", "method", "duration_ms", "error_message",
            ]
            writer = csv.DictWriter(buffer, fieldnames=fieldnames)
            writer.writeheader()

            for item in response.items:
                writer.writerow({
                    "timestamp": item.timestamp.isoformat(),
                    "action": item.action,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "user_id": item.user_id,
                    "tenant_id": item.tenant_id,
                    "success": item.success,
                    "ip_address": item.ip_address,
                    "endpoint": item.endpoint,
                    "method": item.method,
                    "duration_ms": item.duration_ms,
                    "error_message": item.error_message,
                })

            content = buffer.getvalue()

        if output:
            with open(output, "w") as f:
                f.write(content)
            success(f"Exported to: {output}")
        else:
            click.echo(content)

        success(f"Export complete: {len(response.items)} entries")


@audit.command(name="cleanup")
@click.option(
    "--days",
    default=90,
    type=int,
    help="Delete entries older than this many days (default: 90)",
)
@click.option(
    "--tenant-id",
    "-t",
    help="Only cleanup for specific tenant",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without deleting",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation",
)
@coro
async def cleanup_logs(days: int, tenant_id: str | None, dry_run: bool, force: bool) -> None:
    """Delete old audit logs.

    Use with caution - this permanently deletes audit data.
    """
    from datetime import UTC

    from sqlalchemy import func, select

    from example_service.features.audit.models import AuditLog
    from example_service.features.audit.service import AuditService
    from example_service.infra.database.session import async_sessionmaker

    header("Audit Log Cleanup")

    before_date = datetime.now(UTC) - timedelta(days=days)
    info(f"Deleting entries older than: {before_date.strftime('%Y-%m-%d')}")

    async with async_sessionmaker() as session:
        # Count entries to delete
        stmt = select(func.count(AuditLog.id)).where(AuditLog.timestamp < before_date)
        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)

        result = await session.execute(stmt)
        count = result.scalar() or 0

        if count == 0:
            success("No entries to delete")
            return

        if dry_run:
            info(f"Would delete {count:,} entries (dry run)")
            return

        warning(f"This will permanently delete {count:,} audit entries!")

        if not force:
            if not click.confirm("Continue?"):
                info("Cleanup cancelled")
                return

        service = AuditService(session)
        deleted = await service.delete_old_logs(before_date, tenant_id)

        success(f"Deleted {deleted:,} audit entries")
