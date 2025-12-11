"""Background task management commands.

This module provides comprehensive CLI commands for managing Taskiq background tasks:

Task Execution:
- list         - List registered tasks
- run          - Trigger tasks manually with arguments
- status       - Check task status by ID
- result       - Get task results

Task Tracking & Monitoring:
- track        - View statistics with advanced filtering
- watch        - Real-time monitoring with auto-refresh
- history      - Detailed task execution history with pagination
- details      - Inspect specific task execution
- failures     - Quick view of recent failures

Worker Management:
- worker       - Start a Taskiq worker process

Features:
- Advanced filtering (task name, status, worker, duration)
- Real-time monitoring with configurable refresh
- JSON export for all commands
- Color-coded output for better readability
- Pagination support for large result sets
- Full error tracebacks for debugging
"""

import sys
from typing import Any

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


@click.group(name="tasks")
def tasks() -> None:
    """Background task management commands."""


@tasks.command(name="list")
@coro
async def list_tasks() -> None:
    """List all registered background tasks."""
    header("Registered Background Tasks")

    try:
        from example_service.infra.tasks.broker import broker

        if broker is None:
            warning("Taskiq broker is not configured")
            info("Ensure RabbitMQ and Redis are configured in your environment")
            return

        # Get all registered tasks
        registered_tasks = list(broker.available_tasks.keys())  # type: ignore[attr-defined]

        if not registered_tasks:
            info("No tasks registered")
            return

        # Group tasks by module
        task_groups: dict[str, list[str]] = {}
        for task_name in sorted(registered_tasks):
            parts = task_name.rsplit(":", 1)
            if len(parts) == 2:
                module, name = parts
                module_short = module.split(".")[-1] if "." in module else module
            else:
                module_short = "default"
                name = task_name

            if module_short not in task_groups:
                task_groups[module_short] = []
            task_groups[module_short].append(name)

        click.echo()
        for module, task_list in sorted(task_groups.items()):
            section(f"Module: {module}")
            for task_name in task_list:
                click.echo(f"  - {task_name}")
            click.echo()

        success(f"Total: {len(registered_tasks)} tasks registered")

    except ImportError as e:
        error(f"Failed to import task broker: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to list tasks: {e}")
        sys.exit(1)


@tasks.command(name="run")
@click.argument("task_name")
@click.option(
    "--arg",
    "-a",
    multiple=True,
    help="Task arguments as key=value pairs (e.g., -a max_age_hours=12)",
)
@click.option(
    "--wait/--no-wait",
    default=False,
    help="Wait for task completion and show result",
)
@click.option(
    "--timeout",
    default=60,
    type=int,
    help="Timeout in seconds when waiting for result (default: 60)",
)
@coro
async def run_task(task_name: str, arg: tuple, wait: bool, timeout: int) -> None:
    """Manually trigger a background task.

    TASK_NAME is the name of the task to run (e.g., cleanup_temp_files, backup_database).

    Examples:
      example-service tasks run cleanup_temp_files
      example-service tasks run cleanup_temp_files -a max_age_hours=12
      example-service tasks run backup_database --wait
    """
    info(f"Triggering task: {task_name}")

    try:
        from example_service.infra.tasks.broker import broker

        if broker is None:
            error("Taskiq broker is not configured")
            info("Ensure RabbitMQ and Redis are configured")
            sys.exit(1)

        # Parse arguments
        kwargs: dict[str, Any] = {}
        for a in arg:
            if "=" not in a:
                error(f"Invalid argument format: {a} (expected key=value)")
                sys.exit(1)
            key, value = a.split("=", 1)
            # Try to parse as int or float, otherwise keep as string
            try:
                kwargs[key] = int(value)
            except ValueError:
                try:
                    kwargs[key] = float(value)
                except ValueError:
                    # Handle boolean values
                    if value.lower() in ("true", "yes", "1"):
                        kwargs[key] = True
                    elif value.lower() in ("false", "no", "0"):
                        kwargs[key] = False
                    else:
                        kwargs[key] = value

        # Find the task
        task_func = None
        for full_name, task in broker.available_tasks.items():  # type: ignore[attr-defined]
            if full_name.endswith(f":{task_name}") or full_name == task_name:
                task_func = task
                break

        if task_func is None:
            error(f"Task '{task_name}' not found")
            info("Use 'example-service tasks list' to see available tasks")
            sys.exit(1)

        # Start broker if needed
        await broker.startup()

        try:
            # Trigger the task
            if kwargs:
                info(f"Arguments: {kwargs}")
                task_handle = await task_func.kiq(**kwargs)
            else:
                task_handle = await task_func.kiq()

            success("Task triggered successfully!")
            click.echo(f"  Task ID: {task_handle.task_id}")

            if wait:
                info(f"Waiting for result (timeout: {timeout}s)...")
                try:
                    result = await task_handle.wait_result(timeout=timeout)
                    if result.is_err:
                        error(f"Task failed: {result.error}")
                    else:
                        success("Task completed successfully!")
                        click.echo(f"  Result: {result.return_value}")
                except TimeoutError:
                    warning(f"Timeout waiting for result after {timeout}s")
                    info(
                        f"Task may still be running. Check with: example-service tasks status {task_handle.task_id}",
                    )

        finally:
            await broker.shutdown()

    except ImportError as e:
        error(f"Failed to import task modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to run task: {e}")
        sys.exit(1)


@tasks.command(name="status")
@click.argument("task_id")
@coro
async def task_status(task_id: str) -> None:
    """Check the status of a task by ID.

    TASK_ID is the UUID of the task returned when it was triggered.
    """
    info(f"Checking status for task: {task_id}")

    try:
        from example_service.infra.tasks.broker import broker

        if broker is None:
            error("Taskiq broker is not configured")
            sys.exit(1)

        await broker.startup()

        try:
            result = await broker.result_backend.get_result(task_id)

            if result is None:
                warning("Task result not found")
                info("The task may still be running or the result has expired")
                return

            click.echo()
            click.echo(f"  Task ID:   {task_id}")
            click.echo(f"  Status:    {'Error' if result.is_err else 'Completed'}")

            if result.is_err:
                click.secho(f"  Error:     {result.error}", fg="red")
            else:
                click.echo(f"  Result:    {result.return_value}")

            if hasattr(result, "execution_time") and result.execution_time:
                click.echo(f"  Duration:  {result.execution_time:.2f}s")

        finally:
            await broker.shutdown()

    except Exception as e:
        error(f"Failed to get task status: {e}")
        sys.exit(1)


@tasks.command(name="result")
@click.argument("task_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml", "text"]),
    default="text",
    help="Output format",
)
@coro
async def task_result(task_id: str, output_format: str) -> None:
    """Get the result of a completed task.

    TASK_ID is the UUID of the task returned when it was triggered.
    """
    try:
        from example_service.infra.tasks.broker import broker

        if broker is None:
            error("Taskiq broker is not configured")
            sys.exit(1)

        await broker.startup()

        try:
            result = await broker.result_backend.get_result(task_id)

            if result is None:
                warning("Task result not found")
                sys.exit(1)

            if result.is_err:
                error(f"Task failed: {result.error}")
                sys.exit(1)

            # Format output
            if output_format == "json":
                import json

                click.echo(json.dumps(result.return_value, indent=2, default=str))
            elif output_format == "yaml":
                try:
                    import yaml

                    click.echo(yaml.dump(result.return_value, default_flow_style=False))
                except ImportError:
                    error("PyYAML is not installed. Use --format json instead.")
                    sys.exit(1)
            else:
                click.echo(result.return_value)

        finally:
            await broker.shutdown()

    except Exception as e:
        error(f"Failed to get task result: {e}")
        sys.exit(1)


@tasks.command(name="track")
@click.option(
    "--hours",
    "-h",
    default=24,
    type=int,
    help="Number of hours to include in statistics (default: 24)",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON instead of formatted text",
)
@click.option(
    "--running",
    is_flag=True,
    help="Show currently running tasks instead of statistics",
)
@click.option(
    "--task",
    "-t",
    "task_name",
    default=None,
    help="Filter by task name",
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(["success", "failure", "running"], case_sensitive=False),
    default=None,
    help="Filter by task status",
)
@click.option(
    "--worker",
    "-w",
    "worker_id",
    default=None,
    help="Filter by worker ID",
)
@click.option(
    "--min-duration",
    type=int,
    default=None,
    help="Filter tasks with duration >= N milliseconds",
)
@click.option(
    "--max-duration",
    type=int,
    default=None,
    help="Filter tasks with duration <= N milliseconds",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=100,
    help="Maximum number of results (default: 100)",
)
@coro
async def track_tasks(
    hours: int,
    output_json: bool,
    running: bool,
    task_name: str | None,
    status: str | None,
    worker_id: str | None,
    min_duration: int | None,
    max_duration: int | None,
    limit: int,
) -> None:
    """Show task execution statistics and tracking information.

    This command displays statistics about task executions from the tracking
    backend (Redis or PostgreSQL), including success/failure rates, execution
    times, and task breakdowns.

    Examples:
      example-service tasks track                    # Show stats for last 24 hours
      example-service tasks track --hours 48         # Show stats for last 48 hours
      example-service tasks track --task backup_db   # Filter by task name
      example-service tasks track --status failure   # Show only failures
      example-service tasks track --worker worker-01 # Filter by worker
      example-service tasks track --min-duration 5000 # Show slow tasks (>5s)
      example-service tasks track --json             # Output as JSON
      example-service tasks track --running          # Show currently running tasks
    """
    try:
        from datetime import UTC, datetime, timedelta

        from example_service.infra.tasks import get_tracker, start_tracker, stop_tracker

        # Initialize tracking backend
        await start_tracker()
        tracker = get_tracker()

        if tracker is None:
            warning("Task tracking is not configured")
            info("Enable tracking by configuring TASKIQ_TRACKING_BACKEND in settings")
            sys.exit(1)

        if not tracker.is_connected:
            error("Tracker is not connected to backend")
            info("Check your Redis or PostgreSQL configuration")
            sys.exit(1)

        try:
            # Check if any filters are applied
            has_filters = any(
                [task_name, status, worker_id, min_duration, max_duration],
            )

            if running:
                # Show running tasks
                running_tasks = await tracker.get_running_tasks()
                if output_json:
                    import json

                    click.echo(json.dumps(running_tasks, indent=2, default=str))
                else:
                    _print_running_tasks(running_tasks)
            elif has_filters:
                # Show filtered task history
                created_after = (
                    (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
                    if hours
                    else None
                )

                history = await tracker.get_task_history(
                    limit=limit,
                    task_name=task_name,
                    status=status,
                    worker_id=worker_id,
                    min_duration_ms=min_duration,
                    max_duration_ms=max_duration,
                    created_after=created_after,
                )

                if output_json:
                    import json

                    click.echo(json.dumps(history, indent=2, default=str))
                else:
                    _print_task_history(history, task_name, status, worker_id)
            else:
                # Show statistics
                stats = await tracker.get_stats(hours=hours)
                if output_json:
                    import json

                    click.echo(json.dumps(stats, indent=2, default=str))
                else:
                    _print_stats(stats, hours)

        finally:
            await stop_tracker()

    except ImportError as e:
        error(f"Failed to import tracking modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to retrieve tracking data: {e}")
        sys.exit(1)


def _print_stats(stats: dict[str, Any], hours: int) -> None:
    """Print statistics in a human-readable format.

    Args:
        stats: Statistics dictionary from the tracker.
        hours: Number of hours covered by the statistics.
    """
    header(f"Task Execution Statistics (Last {hours} hours)")
    click.echo()

    total = stats.get("total_count", 0)
    success = stats.get("success_count", 0)
    failure = stats.get("failure_count", 0)
    running_count = stats.get("running_count", 0)
    cancelled = stats.get("cancelled_count", 0)

    # Overall statistics
    section("Overall")
    click.echo(f"  Total Tasks:      {total}")
    click.echo(f"  Successful:       {success} ({_pct(success, total)})")
    click.echo(f"  Failed:           {failure} ({_pct(failure, total)})")
    click.echo(f"  Running:          {running_count}")
    click.echo(f"  Cancelled:        {cancelled}")
    click.echo()

    # Average duration
    avg_duration = stats.get("avg_duration_ms")
    if avg_duration is not None:
        section("Performance")
        click.echo(f"  Avg Duration:     {avg_duration:.2f}ms")
        click.echo()

    # Tasks by name
    by_task = stats.get("by_task_name", {})
    if by_task:
        section("Tasks by Name")
        for task_name, count in sorted(by_task.items(), key=lambda x: -x[1]):
            click.echo(f"  {task_name:40} {count:>5}")
        click.echo()

    if total > 0:
        success(f"Processed {total} tasks with {_pct(success, total)} success rate")
    else:
        info(f"No tasks executed in the last {hours} hours")


def _print_running_tasks(tasks: list[dict[str, Any]]) -> None:
    """Print running tasks in a human-readable format.

    Args:
        tasks: List of running task records.
    """
    header("Currently Running Tasks")
    click.echo()

    if not tasks:
        info("No tasks are currently running")
        return

    for task in tasks:
        task_id = task.get("task_id", "unknown")[:12]
        task_name = task.get("task_name", "unknown")
        running_for = task.get("running_for_ms", 0)
        worker_id = task.get("worker_id", "unknown")

        running_seconds = running_for / 1000

        section(f"Task: {task_name}")
        click.echo(f"  ID:           {task_id}")
        click.echo(f"  Running for:  {running_seconds:.1f}s")
        click.echo(f"  Worker:       {worker_id}")
        click.echo()

    success(f"Found {len(tasks)} running task(s)")


def _pct(part: int, total: int) -> str:
    """Calculate percentage string.

    Args:
        part: Part value.
        total: Total value.

    Returns:
        Formatted percentage string.
    """
    if total == 0:
        return "0.0%"
    return f"{(part / total * 100):.1f}%"


def _print_task_history(
    history: list[dict[str, Any]],
    task_name: str | None,
    status_filter: str | None,
    worker_id: str | None,
) -> None:
    """Print task history in a human-readable format.

    Args:
        history: List of task execution records.
        task_name: Task name filter (for display).
        status_filter: Status filter (for display).
        worker_id: Worker ID filter (for display).
    """
    # Build title with filters
    title_parts = ["Task History"]
    filters = []
    if task_name:
        filters.append(f"task={task_name}")
    if status_filter:
        filters.append(f"status={status_filter}")
    if worker_id:
        filters.append(f"worker={worker_id}")

    if filters:
        title_parts.append(f"({', '.join(filters)})")

    header(" ".join(title_parts))
    click.echo()

    if not history:
        info("No tasks match the specified filters")
        return

    for task_record in history:
        task_id = task_record.get("task_id", "unknown")[:12]
        name = task_record.get("task_name", "unknown")
        task_status = task_record.get("status", "unknown")
        duration = task_record.get("duration_ms")
        started = task_record.get("started_at", "unknown")
        worker = task_record.get("worker_id", "unknown")

        # Color-code by status
        if task_status == "success":
            status_display = click.style("✓ SUCCESS", fg="green", bold=True)
        elif task_status == "failure":
            status_display = click.style("✗ FAILURE", fg="red", bold=True)
        elif task_status == "running":
            status_display = click.style("● RUNNING", fg="yellow", bold=True)
        else:
            status_display = task_status.upper()

        section(f"{name} [{task_id}]")
        click.echo(f"  Status:       {status_display}")
        click.echo(f"  Started:      {started}")
        if duration is not None:
            duration_sec = duration / 1000
            click.echo(f"  Duration:     {duration_sec:.2f}s")
        click.echo(f"  Worker:       {worker}")

        # Show error message for failures
        if task_status == "failure":
            error_msg = task_record.get("error_message")
            error_type = task_record.get("error_type")
            if error_type:
                click.echo(f"  Error Type:   {error_type}")
            if error_msg:
                click.echo(f"  Error:        {error_msg[:100]}...")

        click.echo()

    success(f"Found {len(history)} task(s)")


@tasks.command(name="worker")
@click.option(
    "--concurrency",
    "-c",
    default=4,
    type=int,
    help="Number of concurrent workers (default: 4)",
)
@click.option(
    "--queue",
    "-q",
    default=None,
    help="Queue name to process (default: all)",
)
def start_worker(concurrency: int, queue: str | None) -> None:
    """Start a Taskiq worker process.

    This runs the Taskiq worker to process background tasks from the queue.
    """
    import subprocess

    info(f"Starting Taskiq worker (concurrency: {concurrency})")

    cmd = [
        "taskiq",
        "worker",
        "example_service.infra.tasks.broker:broker",
        "-w",
        str(concurrency),
    ]

    if queue:
        cmd.extend(["--queue", queue])

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        info("Worker stopped")
    except FileNotFoundError:
        error("taskiq command not found. Install with: pip install taskiq")
        sys.exit(1)


@tasks.command(name="watch")
@click.option(
    "--interval",
    "-i",
    default=2,
    type=int,
    help="Refresh interval in seconds (default: 2)",
)
@click.option(
    "--running-only",
    is_flag=True,
    help="Show only running tasks",
)
@coro
async def watch_tasks(interval: int, running_only: bool) -> None:
    """Watch task execution in real-time (like Unix 'watch' command).

    This command continuously refreshes the display showing either running tasks
    or recent statistics. Press Ctrl+C to exit.

    Examples:
      example-service tasks watch                # Watch stats (2s refresh)
      example-service tasks watch --interval 5   # Custom refresh rate
      example-service tasks watch --running-only # Watch only running tasks
    """
    import asyncio
    import os
    from datetime import UTC, datetime

    try:
        from example_service.infra.tasks import get_tracker, start_tracker, stop_tracker

        # Initialize tracking backend once
        await start_tracker()
        tracker = get_tracker()

        if tracker is None:
            warning("Task tracking is not configured")
            info("Enable tracking by configuring TASKIQ_TRACKING_BACKEND in settings")
            sys.exit(1)

        if not tracker.is_connected:
            error("Tracker is not connected to backend")
            info("Check your Redis or PostgreSQL configuration")
            sys.exit(1)

        try:
            iteration = 0
            while True:
                # Clear screen (cross-platform)
                os.system("cls" if os.name == "nt" else "clear")

                # Fetch and display current state
                if running_only:
                    tasks_list = await tracker.get_running_tasks()
                    _print_running_tasks(tasks_list)
                else:
                    stats = await tracker.get_stats(hours=1)
                    _print_stats(stats, 1)

                # Show refresh info
                now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                click.echo()
                click.secho(
                    f"[Refreshing every {interval}s - Last update: {now} - Press Ctrl+C to exit]",
                    fg="cyan",
                    dim=True,
                )

                iteration += 1
                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            click.echo("\n")
            info("Watch stopped")
        finally:
            await stop_tracker()

    except ImportError as e:
        error(f"Failed to import tracking modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to watch tasks: {e}")
        sys.exit(1)


@tasks.command(name="history")
@click.option(
    "--limit",
    "-l",
    default=50,
    type=int,
    help="Maximum number of results (default: 50)",
)
@click.option(
    "--offset",
    "-o",
    default=0,
    type=int,
    help="Number of results to skip (default: 0)",
)
@click.option(
    "--task",
    "-t",
    "task_name",
    default=None,
    help="Filter by task name",
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(["success", "failure", "running"], case_sensitive=False),
    default=None,
    help="Filter by task status",
)
@click.option(
    "--worker",
    "-w",
    "worker_id",
    default=None,
    help="Filter by worker ID",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
@coro
async def task_history(
    limit: int,
    offset: int,
    task_name: str | None,
    status: str | None,
    worker_id: str | None,
    output_json: bool,
) -> None:
    """Show detailed task execution history with pagination.

    This command shows a detailed list of recent task executions with support
    for filtering and pagination.

    Examples:
      example-service tasks history                  # Last 50 tasks
      example-service tasks history --limit 100      # Last 100 tasks
      example-service tasks history --task backup_db # Filter by task
      example-service tasks history --status failure # Show only failures
      example-service tasks history --offset 50 --limit 50  # Next page
    """
    try:
        from example_service.infra.tasks import get_tracker, start_tracker, stop_tracker

        await start_tracker()
        tracker = get_tracker()

        if tracker is None:
            warning("Task tracking is not configured")
            sys.exit(1)

        if not tracker.is_connected:
            error("Tracker is not connected to backend")
            sys.exit(1)

        try:
            history = await tracker.get_task_history(
                limit=limit,
                offset=offset,
                task_name=task_name,
                status=status,
                worker_id=worker_id,
            )

            if output_json:
                import json

                click.echo(json.dumps(history, indent=2, default=str))
            else:
                _print_task_history(history, task_name, status, worker_id)

                # Show pagination info
                if offset > 0 or len(history) == limit:
                    click.echo()
                    section("Pagination")
                    if offset > 0:
                        prev_offset = max(0, offset - limit)
                        click.echo(f"  Previous page: --offset {prev_offset} --limit {limit}")
                    if len(history) == limit:
                        next_offset = offset + limit
                        click.echo(f"  Next page:     --offset {next_offset} --limit {limit}")

        finally:
            await stop_tracker()

    except ImportError as e:
        error(f"Failed to import tracking modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to retrieve task history: {e}")
        sys.exit(1)


@tasks.command(name="details")
@click.argument("task_id")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
@coro
async def task_details(task_id: str, output_json: bool) -> None:
    """Show detailed information for a specific task execution.

    TASK_ID is the UUID of the task execution to inspect.

    Examples:
      example-service tasks details abc123...
      example-service tasks details abc123... --json
    """
    try:
        from example_service.infra.tasks import get_tracker, start_tracker, stop_tracker

        await start_tracker()
        tracker = get_tracker()

        if tracker is None:
            warning("Task tracking is not configured")
            sys.exit(1)

        if not tracker.is_connected:
            error("Tracker is not connected to backend")
            sys.exit(1)

        try:
            details = await tracker.get_task_details(task_id)

            if details is None:
                error(f"Task '{task_id}' not found")
                sys.exit(1)

            if output_json:
                import json

                click.echo(json.dumps(details, indent=2, default=str))
            else:
                _print_task_details(details)

        finally:
            await stop_tracker()

    except ImportError as e:
        error(f"Failed to import tracking modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to retrieve task details: {e}")
        sys.exit(1)


@tasks.command(name="failures")
@click.option(
    "--hours",
    "-h",
    default=24,
    type=int,
    help="Number of hours to look back (default: 24)",
)
@click.option(
    "--limit",
    "-l",
    default=20,
    type=int,
    help="Maximum number of failures to show (default: 20)",
)
@click.option(
    "--task",
    "-t",
    "task_name",
    default=None,
    help="Filter by task name",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
@coro
async def task_failures(
    hours: int,
    limit: int,
    task_name: str | None,
    output_json: bool,
) -> None:
    """Show recent task failures for quick debugging.

    This command provides a quick view of recent task failures with error
    messages and stack traces.

    Examples:
      example-service tasks failures                # Last 24 hours
      example-service tasks failures --hours 48     # Last 48 hours
      example-service tasks failures --limit 50     # Show more failures
      example-service tasks failures --task backup  # Specific task failures
    """
    try:
        from datetime import UTC, datetime, timedelta

        from example_service.infra.tasks import get_tracker, start_tracker, stop_tracker

        await start_tracker()
        tracker = get_tracker()

        if tracker is None:
            warning("Task tracking is not configured")
            sys.exit(1)

        if not tracker.is_connected:
            error("Tracker is not connected to backend")
            sys.exit(1)

        try:
            created_after = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

            failures = await tracker.get_task_history(
                limit=limit,
                task_name=task_name,
                status="failure",
                created_after=created_after,
            )

            if output_json:
                import json

                click.echo(json.dumps(failures, indent=2, default=str))
            else:
                _print_failures(failures, hours)

        finally:
            await stop_tracker()

    except ImportError as e:
        error(f"Failed to import tracking modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to retrieve failures: {e}")
        sys.exit(1)


def _print_task_details(details: dict[str, Any]) -> None:
    """Print detailed task information.

    Args:
        details: Task execution details dictionary.
    """
    header(f"Task Details: {details.get('task_name', 'Unknown')}")
    click.echo()

    # Basic info
    section("Basic Information")
    click.echo(f"  Task ID:      {details.get('task_id', 'N/A')}")
    click.echo(f"  Task Name:    {details.get('task_name', 'N/A')}")

    task_status = details.get("status", "unknown")
    if task_status == "success":
        status_display = click.style("✓ SUCCESS", fg="green", bold=True)
    elif task_status == "failure":
        status_display = click.style("✗ FAILURE", fg="red", bold=True)
    elif task_status == "running":
        status_display = click.style("● RUNNING", fg="yellow", bold=True)
    else:
        status_display = task_status.upper()

    click.echo(f"  Status:       {status_display}")
    click.echo(f"  Retry Count:  {details.get('retry_count', 0)}")
    click.echo()

    # Timing info
    section("Timing")
    click.echo(f"  Started:      {details.get('started_at', 'N/A')}")
    click.echo(f"  Finished:     {details.get('finished_at', 'N/A')}")
    duration = details.get("duration_ms")
    if duration is not None:
        duration_sec = duration / 1000
        click.echo(f"  Duration:     {duration_sec:.2f}s ({duration}ms)")
    click.echo()

    # Execution info
    section("Execution")
    click.echo(f"  Worker ID:    {details.get('worker_id', 'N/A')}")
    click.echo(f"  Queue:        {details.get('queue_name', 'N/A')}")
    click.echo()

    # Arguments
    task_args = details.get("task_args")
    task_kwargs = details.get("task_kwargs")
    if task_args or task_kwargs:
        section("Arguments")
        if task_args:
            click.echo(f"  Args:         {task_args}")
        if task_kwargs:
            click.echo(f"  Kwargs:       {task_kwargs}")
        click.echo()

    # Result/Error
    if task_status == "success":
        return_value = details.get("return_value")
        if return_value is not None:
            section("Result")
            click.echo(f"  {return_value}")
            click.echo()
    elif task_status == "failure":
        section("Error Information")
        error_type = details.get("error_type")
        error_msg = details.get("error_message")
        error_traceback = details.get("error_traceback")

        if error_type:
            click.echo(f"  Error Type:   {error_type}")
        if error_msg:
            click.echo(f"  Error Message:")
            click.echo(f"    {error_msg}")
        if error_traceback:
            click.echo()
            click.echo("  Traceback:")
            for line in error_traceback.split("\n"):
                if line.strip():
                    click.echo(f"    {line}")
        click.echo()

    # Labels/Metadata
    labels = details.get("labels")
    if labels:
        section("Labels")
        for key, value in labels.items():
            click.echo(f"  {key}: {value}")
        click.echo()


def _print_failures(failures: list[dict[str, Any]], hours: int) -> None:
    """Print task failures in a compact, readable format.

    Args:
        failures: List of failed task records.
        hours: Number of hours covered.
    """
    header(f"Recent Task Failures (Last {hours} hours)")
    click.echo()

    if not failures:
        success(f"No task failures in the last {hours} hours! 🎉")
        return

    for idx, failure in enumerate(failures, 1):
        task_id = failure.get("task_id", "unknown")[:12]
        name = failure.get("task_name", "unknown")
        started = failure.get("started_at", "unknown")
        error_type = failure.get("error_type", "Unknown")
        error_msg = failure.get("error_message", "No error message")
        duration = failure.get("duration_ms")

        click.secho(f"[{idx}] {name} ({task_id})", fg="red", bold=True)
        click.echo(f"    Started:    {started}")
        if duration is not None:
            duration_sec = duration / 1000
            click.echo(f"    Duration:   {duration_sec:.2f}s")
        click.echo(f"    Error:      {error_type}")
        click.echo(f"    Message:    {error_msg[:150]}...")
        click.echo()

    warning(f"Found {len(failures)} failure(s)")
    click.echo()
    info(f"Use 'example-service tasks details <task-id>' for full error traceback")
