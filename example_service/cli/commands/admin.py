"""Database administration commands.

This module provides CLI commands for database administration, including:
- Health checks and status monitoring
- Database statistics and metrics
- Active connection monitoring
- Table and index analysis
- Admin operation audit logs

Example:
    # Check overall database health
    example-service admin health

    # Show detailed database statistics
    example-service admin stats

    # List active connections
    example-service admin connections --limit 20

    # Show table sizes
    example-service admin table-sizes

    # Check index health
    example-service admin index-health --table users

    # View audit logs
    example-service admin audit-logs --days 30
"""

from datetime import UTC, datetime, timedelta
import json
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


@click.group(name="admin")
def admin() -> None:
    """Database administration commands.

    Monitor database health, view statistics, analyze performance,
    and manage database maintenance operations.
    """


# =============================================================================
# Health & Status Commands
# =============================================================================


@admin.command()
@coro
async def health() -> None:
    """Check database health status.

    Displays comprehensive health information including:
    - Connection pool usage
    - Cache hit ratio
    - Database size
    - Replication lag (if applicable)
    - Overall health status (HEALTHY/DEGRADED/UNHEALTHY)

    Example:
        example-service admin health
    """
    header("Database Health Check")

    try:
        from example_service.core.database.admin_utils import format_bytes
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Get health status
            health_result = await service.get_health()

            click.echo()
            section("Health Status")

            # Overall status with color coding
            status = health_result.status
            if status == "HEALTHY":
                click.echo("  Overall Status: ", nl=False)
                click.secho("HEALTHY", fg="green", bold=True)
            elif status == "DEGRADED":
                click.echo("  Overall Status: ", nl=False)
                click.secho("DEGRADED", fg="yellow", bold=True)
            else:
                click.echo("  Overall Status: ", nl=False)
                click.secho("UNHEALTHY", fg="red", bold=True)

            click.echo()

            # Connection pool statistics
            section("Connection Pool")
            pool_stats = health_result.details.get("pool_stats", {})
            click.echo(f"  Active:        {pool_stats.get('active', 'N/A')}")
            click.echo(f"  Idle:          {pool_stats.get('idle', 'N/A')}")
            click.echo(f"  Total:         {pool_stats.get('total', 'N/A')}")
            click.echo(f"  Max Size:      {pool_stats.get('max_size', 'N/A')}")

            # Cache hit ratio
            section("Cache Performance")
            cache_ratio = health_result.details.get("cache_hit_ratio", 0.0)
            cache_healthy = cache_ratio >= 85.0

            click.echo("  Hit Ratio:     ", nl=False)
            if cache_healthy:
                click.secho(f"{cache_ratio:.2f}%", fg="green")
            else:
                click.secho(f"{cache_ratio:.2f}%", fg="yellow")
                warning("Cache hit ratio is below optimal threshold (85%)")

            # Database size
            section("Storage")
            db_size = health_result.details.get("database_size", 0)
            click.echo(f"  Database Size: {format_bytes(db_size)}")

            # Warnings
            warnings_list = health_result.details.get("warnings", [])
            if warnings_list:
                click.echo()
                section("Warnings")
                for warn_msg in warnings_list:
                    warning(warn_msg)

            click.echo()
            if status == "HEALTHY":
                success("Database is healthy and operating normally")
            elif status == "DEGRADED":
                warning("Database is operational but has some issues")
            else:
                error("Database health check failed - immediate attention required")

    except Exception as e:
        error(f"Failed to get database health: {e}")
        sys.exit(1)


# =============================================================================
# Statistics Commands
# =============================================================================


@admin.command()
@click.option("--format", type=click.Choice(["table", "json"]), default="table")
@coro
async def stats(format: str) -> None:
    """Show database statistics.

    Displays detailed database metrics including table counts,
    index counts, transaction rates, and cache statistics.

    Example:
        example-service admin stats
        example-service admin stats --format json
    """
    header("Database Statistics")

    try:
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Get database statistics
            stats_result = await service.get_statistics()

            if format == "json":
                # JSON output
                output = {
                    "table_count": stats_result.table_count,
                    "index_count": stats_result.index_count,
                    "database_size": stats_result.database_size,
                    "cache_hit_ratio": stats_result.cache_hit_ratio,
                    "active_connections": stats_result.active_connections,
                    "max_connections": stats_result.max_connections,
                    "transaction_rate": stats_result.transaction_rate,
                }
                click.echo(json.dumps(output, indent=2, default=str))
                return

            # Table format
            click.echo()
            section("Schema Statistics")
            click.echo(f"  Total Tables:       {stats_result.table_count}")
            click.echo(f"  Total Indexes:      {stats_result.index_count}")

            section("Performance Metrics")
            click.echo(f"  Cache Hit Ratio:    {stats_result.cache_hit_ratio:.2f}%")
            click.echo(f"  Transaction Rate:   {stats_result.transaction_rate:.2f}/sec")

            section("Connection Statistics")
            click.echo(f"  Active Connections: {stats_result.active_connections}")
            click.echo(f"  Max Connections:    {stats_result.max_connections}")
            utilization = (
                (stats_result.active_connections / stats_result.max_connections * 100)
                if stats_result.max_connections > 0
                else 0
            )
            click.echo(f"  Utilization:        {utilization:.1f}%")

            click.echo()
            success("Statistics retrieved successfully")

    except Exception as e:
        error(f"Failed to get database statistics: {e}")
        sys.exit(1)


# =============================================================================
# Connection Monitoring Commands
# =============================================================================


@admin.command()
@click.option("--limit", type=int, default=10, help="Number of connections to show")
@coro
async def connections(limit: int) -> None:
    """List active database connections.

    Shows currently active queries with duration and state.

    Example:
        example-service admin connections
        example-service admin connections --limit 20
    """
    header("Active Database Connections")

    try:
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Get active connections
            connections_list = await service.get_active_connections(limit=limit)

            if not connections_list:
                info("No active connections found")
                return

            click.echo()
            # Table header
            click.echo(
                f"  {'PID':<8} {'User':<15} {'State':<12} {'Duration':<12} {'Query Preview'}",
            )
            click.echo("  " + "-" * 90)

            # Connection rows
            for conn in connections_list:
                # Color-code state
                state = conn.state or "N/A"
                state_color = (
                    "green"
                    if state == "active"
                    else "yellow"
                    if state == "idle"
                    else "red"
                )
                state_str = click.style(state, fg=state_color)

                # Format duration
                duration = conn.duration or "N/A"
                if isinstance(duration, (int, float)):
                    if duration < 60:
                        duration_str = f"{duration:.1f}s"
                    elif duration < 3600:
                        duration_str = f"{duration/60:.1f}m"
                    else:
                        duration_str = f"{duration/3600:.1f}h"
                else:
                    duration_str = str(duration)

                # Truncate query preview
                query = (conn.query_preview or "")[:40]

                click.echo(
                    f"  {conn.pid:<8} {(conn.username or 'N/A'):<15} "
                    f"{state_str:<21} {duration_str:<12} {query}",
                )

            click.echo()
            success(f"Total: {len(connections_list)} connections (showing up to {limit})")

    except Exception as e:
        error(f"Failed to get active connections: {e}")
        sys.exit(1)


# =============================================================================
# Table Analysis Commands
# =============================================================================


@admin.command(name="table-sizes")
@click.option("--limit", type=int, default=20, help="Number of tables to show")
@coro
async def table_sizes(limit: int) -> None:
    """Show table sizes sorted by total size.

    Displays tables with their row counts and size breakdowns.

    Example:
        example-service admin table-sizes
        example-service admin table-sizes --limit 50
    """
    header("Table Sizes")

    try:
        from example_service.core.database.admin_utils import format_bytes
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Get table sizes
            table_sizes_list = await service.get_table_sizes(limit=limit)

            if not table_sizes_list:
                info("No tables found")
                return

            click.echo()
            # Table header
            click.echo(
                f"  {'Table Name':<35} {'Rows':<12} {'Table Size':<15} {'Index Size':<15} {'Total Size'}",
            )
            click.echo("  " + "-" * 100)

            # Table rows
            for table in table_sizes_list:
                table_size = format_bytes(table.table_size)
                index_size = format_bytes(table.index_size)
                total_size = format_bytes(table.total_size)
                row_count = f"{table.row_count:,}" if table.row_count else "N/A"

                click.echo(
                    f"  {table.table_name:<35} {row_count:<12} "
                    f"{table_size:<15} {index_size:<15} {total_size}",
                )

            click.echo()
            success(f"Showing top {len(table_sizes_list)} tables by size")

    except Exception as e:
        error(f"Failed to get table sizes: {e}")
        sys.exit(1)


# =============================================================================
# Index Analysis Commands
# =============================================================================


@admin.command(name="index-health")
@click.option("--table", type=str, default=None, help="Filter by table name")
@coro
async def index_health(table: str | None) -> None:
    """Check index health and usage statistics.

    Shows index sizes, scan counts, and potential issues.

    Example:
        example-service admin index-health
        example-service admin index-health --table users
    """
    header("Index Health")

    try:
        from example_service.core.database.admin_utils import format_bytes
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Get index health
            index_health_list = await service.get_index_health(table_name=table)

            if not index_health_list:
                msg = f"No indexes found for table '{table}'" if table else "No indexes found"
                info(msg)
                return

            click.echo()
            if table:
                info(f"Showing indexes for table: {table}")
                click.echo()

            # Table header
            click.echo(
                f"  {'Index Name':<35} {'Table':<25} {'Size':<12} {'Scans':<10} {'Status'}",
            )
            click.echo("  " + "-" * 95)

            # Index rows
            for index in index_health_list:
                size = format_bytes(index.size)
                scans = f"{index.scan_count:,}" if index.scan_count else "0"

                # Determine status based on usage
                if index.scan_count == 0 and index.size > 1024 * 1024:  # > 1 MB unused
                    status = click.style("UNUSED", fg="red")
                elif index.scan_count < 10:
                    status = click.style("LOW USAGE", fg="yellow")
                else:
                    status = click.style("HEALTHY", fg="green")

                click.echo(
                    f"  {index.index_name:<35} {index.table_name:<25} "
                    f"{size:<12} {scans:<10} {status}",
                )

            click.echo()
            success(f"Analyzed {len(index_health_list)} indexes")

            # Show recommendations
            unused_indexes = [
                idx for idx in index_health_list if idx.scan_count == 0 and idx.size > 1024 * 1024
            ]
            if unused_indexes:
                click.echo()
                warning(f"Found {len(unused_indexes)} unused index(es) > 1 MB")
                info("Consider dropping unused indexes to save space and improve write performance")

    except Exception as e:
        error(f"Failed to get index health: {e}")
        sys.exit(1)


# =============================================================================
# Audit Log Commands
# =============================================================================


@admin.command(name="audit-logs")
@click.option("--action", type=str, default=None, help="Filter by action type")
@click.option("--user", type=str, default=None, help="Filter by user ID")
@click.option("--days", type=int, default=7, help="Number of days to show")
@coro
async def audit_logs(action: str | None, user: str | None, days: int) -> None:
    """View admin operation audit logs.

    Displays recent administrative actions with results and metadata.

    Example:
        example-service admin audit-logs
        example-service admin audit-logs --action vacuum --days 30
        example-service admin audit-logs --user admin@example.com --days 7
    """
    header("Admin Audit Logs")

    try:
        from example_service.core.dependencies import get_db
        from example_service.core.settings import get_admin_settings
        from example_service.features.admin.database.dao import DatabaseAdminDAO
        from example_service.features.admin.database.service import DatabaseAdminService

        async with get_db() as session:
            dao = DatabaseAdminDAO(session)
            settings = get_admin_settings()
            service = DatabaseAdminService(dao, settings)

            # Calculate start time
            start_time = datetime.now(UTC) - timedelta(days=days)

            # Build filters
            filters = {}
            if action:
                filters["action"] = action
            if user:
                filters["user_id"] = user

            # Get audit logs
            audit_logs_list = await service.get_audit_logs(
                start_time=start_time,
                filters=filters,
            )

            if not audit_logs_list:
                info(f"No audit logs found in the last {days} days")
                if action or user:
                    info("Try adjusting your filters or increasing the time range")
                return

            click.echo()
            if action:
                info(f"Filtering by action: {action}")
            if user:
                info(f"Filtering by user: {user}")
            click.echo()

            # Table header
            click.echo(
                f"  {'Timestamp':<20} {'Action':<20} {'Target':<25} {'Result':<10} {'User'}",
            )
            click.echo("  " + "-" * 100)

            # Log rows
            for log in audit_logs_list:
                # Format timestamp
                timestamp = log.timestamp.strftime("%Y-%m-%d %H:%M:%S")

                # Color-code result
                result = log.result or "N/A"
                if result == "SUCCESS":
                    result_str = click.style(result, fg="green")
                elif result == "FAILED":
                    result_str = click.style(result, fg="red")
                else:
                    result_str = result

                # Truncate user
                user_str = (log.user_id or "system")[:30]

                click.echo(
                    f"  {timestamp:<20} {log.action:<20} "
                    f"{log.target:<25} {result_str:<19} {user_str}",
                )

                # Show details if available
                if log.details:
                    details_str = str(log.details)[:80]
                    click.echo(f"    Details: {details_str}")

            click.echo()
            success(f"Showing {len(audit_logs_list)} audit log entries from the last {days} days")

    except Exception as e:
        error(f"Failed to get audit logs: {e}")
        sys.exit(1)


# =============================================================================
# Registration Instructions
# =============================================================================
