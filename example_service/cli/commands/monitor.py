"""Monitoring and observability commands.

This module provides CLI commands for monitoring:
- Application health and status
- Service connectivity checks
- Queue and broker statistics
- Log viewing
"""

import shutil
import sys
from datetime import UTC, datetime
from typing import Any, cast

import click

from example_service.cli.utils import coro, error, header, info, section, success, warning


@click.group(name="monitor")
def monitor() -> None:
    """Monitoring and observability commands."""


@monitor.command(name="status")
@coro
async def application_status() -> None:
    """Show overall application status and health."""
    header("Application Status")

    from example_service.core.settings import get_settings

    settings = get_settings()

    click.echo()
    section("Application Info")
    click.echo(f"  Service:     {settings.app.service_name}")
    click.echo(f"  Version:     {settings.app.version}")
    click.echo(f"  Environment: {settings.app.environment}")
    click.echo(f"  Debug:       {settings.app.debug}")

    # Check all services
    section("Service Health")

    # Database
    db_status = await _check_database()
    _print_status("PostgreSQL", db_status)

    # Redis
    redis_status = await _check_redis()
    _print_status("Redis", redis_status)

    # RabbitMQ
    rabbit_status = await _check_rabbitmq()
    _print_status("RabbitMQ", rabbit_status)

    # Scheduler
    scheduler_status = _check_scheduler()
    _print_status("Scheduler", scheduler_status)

    # Overall
    click.echo()
    all_healthy = all(
        s.get("healthy", False)
        for s in [db_status, redis_status, rabbit_status, scheduler_status]
        if s.get("configured", True)
    )

    if all_healthy:
        success("All services are healthy")
    else:
        warning("Some services are unhealthy or not configured")


def _print_status(name: str, status: dict) -> None:
    """Print a service status line."""
    if not status.get("configured", True):
        click.echo(f"  {name:<15} ", nl=False)
        click.secho("Not Configured", fg="yellow")
        return

    healthy = status.get("healthy", False)
    if healthy:
        click.echo(f"  {name:<15} ", nl=False)
        click.secho("Healthy", fg="green", nl=False)
        if status.get("info"):
            click.echo(f" ({status['info']})")
        else:
            click.echo()
    else:
        click.echo(f"  {name:<15} ", nl=False)
        click.secho("Unhealthy", fg="red", nl=False)
        if status.get("error"):
            click.echo(f" - {status['error']}")
        else:
            click.echo()


async def _check_database() -> dict:
    """Check database connectivity."""
    from example_service.core.settings import get_db_settings

    db_settings = get_db_settings()
    if not db_settings.is_configured:
        return {"configured": False}

    try:
        from sqlalchemy import text

        from example_service.infra.database import get_async_session

        async with get_async_session() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar_one()

            # Get version
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            version_short = version.split(",")[0] if version else "Unknown"

            return {"healthy": True, "configured": True, "info": version_short}
    except Exception as e:
        return {"healthy": False, "configured": True, "error": str(e)}


async def _check_redis() -> dict:
    """Check Redis connectivity."""
    from example_service.core.settings import get_redis_settings

    redis_settings = get_redis_settings()
    if not redis_settings.is_configured:
        return {"configured": False}

    try:
        import redis.asyncio as redis

        client = redis.from_url(redis_settings.get_url())
        info_data = await client.info("server")
        await cast("Any", client).aclose()

        version = info_data.get("redis_version", "Unknown")
        return {"healthy": True, "configured": True, "info": f"v{version}"}
    except Exception as e:
        return {"healthy": False, "configured": True, "error": str(e)}


async def _check_rabbitmq() -> dict:
    """Check RabbitMQ connectivity."""
    from example_service.core.settings import get_rabbit_settings

    rabbit_settings = get_rabbit_settings()
    if not rabbit_settings.is_configured:
        return {"configured": False}

    try:
        import aio_pika

        connection = await aio_pika.connect_robust(rabbit_settings.get_url())
        await connection.close()

        return {
            "healthy": True,
            "configured": True,
            "info": f"{rabbit_settings.host}:{rabbit_settings.port}",
        }
    except Exception as e:
        return {"healthy": False, "configured": True, "error": str(e)}


def _check_scheduler() -> dict:
    """Check APScheduler status."""
    try:
        from example_service.infra.tasks.scheduler import scheduler

        if scheduler.running:
            job_count = len(scheduler.get_jobs())
            return {"healthy": True, "configured": True, "info": f"{job_count} jobs"}
        else:
            return {"healthy": False, "configured": True, "error": "Not running"}
    except Exception as e:
        return {"healthy": False, "configured": True, "error": str(e)}


@monitor.command(name="connections")
@coro
async def show_connections() -> None:
    """Show active database connections."""
    header("Database Connections")

    try:
        from sqlalchemy import text

        from example_service.infra.database import get_async_session

        async with get_async_session() as session:
            result = await session.execute(
                text("""
                SELECT
                    pid,
                    usename as username,
                    application_name,
                    client_addr,
                    state,
                    query_start,
                    LEFT(query, 50) as query_preview
                FROM pg_stat_activity
                WHERE datname = current_database()
                ORDER BY query_start DESC NULLS LAST
            """)
            )
            connections = result.fetchall()

            click.echo()
            click.echo(f"  {'PID':<8} {'User':<15} {'State':<12} {'Client':<18} {'Query'}")
            click.echo("  " + "-" * 80)

            for conn in connections:
                state_color = (
                    "green"
                    if conn.state == "active"
                    else "yellow"
                    if conn.state == "idle"
                    else "red"
                )
                state_str = click.style(conn.state or "N/A", fg=state_color)

                client = str(conn.client_addr) if conn.client_addr else "local"
                query = (conn.query_preview or "")[:40]

                click.echo(
                    f"  {conn.pid:<8} {(conn.username or 'N/A'):<15} {state_str:<21} {client:<18} {query}"
                )

            click.echo()
            success(f"Total: {len(connections)} connections")

    except Exception as e:
        error(f"Failed to get connections: {e}")
        sys.exit(1)


@monitor.command(name="queues")
@coro
async def show_queues() -> None:
    """Show RabbitMQ queue statistics."""
    header("Message Queue Statistics")

    from example_service.core.settings import get_rabbit_settings

    rabbit_settings = get_rabbit_settings()
    if not rabbit_settings.is_configured:
        warning("RabbitMQ is not configured")
        return

    try:
        import aio_pika

        connection = await aio_pika.connect_robust(rabbit_settings.get_url())

        async with connection:
            channel = await connection.channel()

            # Get queue info for known queues
            queue_names = [
                rabbit_settings.get_prefixed_queue("taskiq-tasks"),
                rabbit_settings.get_prefixed_queue("echo-service"),
            ]

            click.echo()
            click.echo(f"  {'Queue':<40} {'Messages':<12} {'Consumers':<12}")
            click.echo("  " + "-" * 64)

            for queue_name in queue_names:
                try:
                    queue = await channel.get_queue(queue_name, ensure=False)
                    declaration = await queue.declare()

                    click.echo(
                        f"  {queue_name:<40} {declaration.message_count:<12} {declaration.consumer_count:<12}"
                    )
                except Exception:
                    click.echo(f"  {queue_name:<40} {'N/A':<12} {'N/A':<12}")

        click.echo()

    except Exception as e:
        error(f"Failed to get queue stats: {e}")
        sys.exit(1)


@monitor.command(name="redis")
@coro
async def redis_info() -> None:
    """Show Redis server information and statistics."""
    header("Redis Statistics")

    from example_service.core.settings import get_redis_settings

    redis_settings = get_redis_settings()
    if not redis_settings.is_configured:
        warning("Redis is not configured")
        return

    try:
        import redis.asyncio as redis

        client = redis.from_url(redis_settings.get_url())

        # Server info
        info_server = await client.info("server")
        info_memory = await client.info("memory")
        info_stats = await client.info("stats")
        info_clients = await client.info("clients")
        db_size = await client.dbsize()

        section("Server Info")
        click.echo(f"  Version:        {info_server.get('redis_version', 'N/A')}")
        click.echo(f"  Uptime:         {info_server.get('uptime_in_days', 0)} days")
        click.echo(f"  OS:             {info_server.get('os', 'N/A')}")

        section("Memory")
        used_memory = info_memory.get("used_memory_human", "N/A")
        peak_memory = info_memory.get("used_memory_peak_human", "N/A")
        click.echo(f"  Used Memory:    {used_memory}")
        click.echo(f"  Peak Memory:    {peak_memory}")

        section("Statistics")
        click.echo(f"  Total Keys:     {db_size}")
        click.echo(f"  Connected:      {info_clients.get('connected_clients', 0)} clients")
        click.echo(f"  Total Commands: {info_stats.get('total_commands_processed', 0):,}")
        click.echo(f"  Keyspace Hits:  {info_stats.get('keyspace_hits', 0):,}")
        click.echo(f"  Keyspace Misses:{info_stats.get('keyspace_misses', 0):,}")

        await cast("Any", client).aclose()

    except Exception as e:
        error(f"Failed to get Redis info: {e}")
        sys.exit(1)


@monitor.command(name="metrics")
@coro
async def show_metrics() -> None:
    """Show application metrics summary."""
    header("Application Metrics")

    try:
        from sqlalchemy import func, select, text

        from example_service.core.models.user import User
        from example_service.features.reminders.models import Reminder
        from example_service.infra.database import get_async_session

        async with get_async_session() as session:
            # User metrics
            result = await session.execute(select(func.count()).select_from(User))
            total_users = result.scalar_one()

            result = await session.execute(
                select(func.count()).select_from(User).where(User.is_active == True)  # noqa: E712
            )
            active_users = result.scalar_one()

            section("User Metrics")
            click.echo(f"  Total Users:    {total_users}")
            click.echo(f"  Active Users:   {active_users}")
            click.echo(f"  Inactive Users: {total_users - active_users}")

            # Reminder metrics
            result = await session.execute(select(func.count()).select_from(Reminder))
            total_reminders = result.scalar_one()

            result = await session.execute(
                select(func.count()).select_from(Reminder).where(Reminder.is_completed == True)  # noqa: E712
            )
            completed_reminders = result.scalar_one()

            result = await session.execute(
                select(func.count())
                .select_from(Reminder)
                .where(
                    Reminder.is_completed == False,  # noqa: E712
                    Reminder.remind_at <= datetime.now(UTC),
                )
            )
            overdue_reminders = result.scalar_one()

            section("Reminder Metrics")
            click.echo(f"  Total:          {total_reminders}")
            click.echo(f"  Completed:      {completed_reminders}")
            click.echo(f"  Pending:        {total_reminders - completed_reminders}")
            click.echo(f"  Overdue:        {overdue_reminders}")

            # Database metrics
            result = await session.execute(
                text("""
                SELECT pg_size_pretty(pg_database_size(current_database()))
            """)
            )
            db_size = result.scalar_one()

            section("Database Metrics")
            click.echo(f"  Database Size:  {db_size}")

    except Exception as e:
        error(f"Failed to get metrics: {e}")
        sys.exit(1)


@monitor.command(name="logs")
@click.option(
    "--lines",
    "-n",
    default=50,
    type=int,
    help="Number of lines to show (default: 50)",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    default=False,
    help="Follow log output (like tail -f)",
)
@click.option(
    "--level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default=None,
    help="Filter by log level",
)
def view_logs(lines: int, follow: bool, level: str | None) -> None:
    """View application logs.

    Note: This requires logs to be written to a file.
    Configure LOG_FILE in your environment.
    """
    import subprocess
    from pathlib import Path

    from example_service.core.settings import get_logging_settings

    log_settings = get_logging_settings()

    # Check common log locations
    log_paths = [
        Path(log_settings.log_file)
        if hasattr(log_settings, "log_file") and log_settings.log_file
        else None,
        Path("/var/log/example-service/app.log"),
        Path("logs/app.log"),
        Path("app.log"),
    ]

    log_file = None
    for path in log_paths:
        if path and path.exists():
            log_file = path
            break

    if not log_file:
        warning("No log file found")
        info("Configure LOG_FILE environment variable or check log paths")
        info("Checked locations:")
        for path in log_paths:
            if path:
                click.echo(f"  - {path}")
        return

    info(f"Reading logs from: {log_file}")

    try:
        # Resolve full paths for executables
        tail_path = shutil.which("tail")
        grep_path = shutil.which("grep")

        if not tail_path:
            raise FileNotFoundError("tail command not found")
        if level and not grep_path:
            raise FileNotFoundError("grep command not found")

        cmd = [tail_path]

        if follow:
            cmd.append("-f")
        else:
            cmd.extend(["-n", str(lines)])

        cmd.append(str(log_file))

        if level:
            # Pipe through grep for level filtering
            # tail_path and grep_path are resolved via shutil.which(), level is validated enum
            if grep_path is None:
                raise FileNotFoundError("grep command not found")
            tail_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)  # noqa: S603
            if tail_proc.stdout is None:
                error("Failed to create tail process")
                sys.exit(1)
            grep_proc = subprocess.Popen(  # noqa: S603
                [grep_path, "--line-buffered", level],
                stdin=tail_proc.stdout,
                stdout=subprocess.PIPE,
                text=True,
            )
            tail_proc.stdout.close()

            try:
                if grep_proc.stdout is not None:
                    for line in grep_proc.stdout:
                        click.echo(line, nl=False)
            except KeyboardInterrupt:
                pass
            finally:
                grep_proc.terminate()
        else:
            # tail_path is resolved via shutil.which(), log_file is validated path
            subprocess.run(cmd)  # noqa: S603

    except FileNotFoundError:
        error("tail command not found")
        sys.exit(1)
    except KeyboardInterrupt:
        info("Log viewing stopped")


@monitor.command(name="workers")
@coro
async def show_workers() -> None:
    """Show Taskiq worker status (if available)."""
    header("Worker Status")

    warning("Worker status monitoring requires a running worker process")
    info("Start a worker with: example-service tasks worker")

    from example_service.core.settings import get_rabbit_settings

    rabbit_settings = get_rabbit_settings()
    if not rabbit_settings.is_configured:
        warning("RabbitMQ is not configured - workers cannot run")
        return

    try:
        import aio_pika

        connection = await aio_pika.connect_robust(rabbit_settings.get_url())

        async with connection:
            channel = await connection.channel()

            queue_name = rabbit_settings.get_prefixed_queue("taskiq-tasks")

            try:
                queue = await channel.get_queue(queue_name, ensure=False)
                declaration = await queue.declare()

                section("Task Queue Status")
                click.echo(f"  Queue:           {queue_name}")
                click.echo(f"  Pending Tasks:   {declaration.message_count}")
                click.echo(f"  Active Workers:  {declaration.consumer_count}")

                if declaration.consumer_count == 0:
                    warning("No workers are currently consuming from the task queue")
                    info("Start a worker with: example-service tasks worker")

            except Exception as e:
                warning(f"Could not get queue info: {e}")

    except Exception as e:
        error(f"Failed to check worker status: {e}")
        sys.exit(1)
