"""Background task management commands.

This module provides CLI commands for managing Taskiq background tasks:
- List registered tasks
- Trigger tasks manually
- Check task status and results
- View task queue information
"""

import sys
from typing import Any

import click

from example_service.cli.utils import coro, error, header, info, section, success, warning


@click.group(name="tasks")
def tasks() -> None:
    """Background task management commands."""


@tasks.command(name="list")
@coro
async def list_tasks() -> None:
    """List all registered background tasks."""
    header("Registered Background Tasks")

    try:
        from example_service.tasks.broker import broker

        if broker is None:
            warning("Taskiq broker is not configured")
            info("Ensure RabbitMQ and Redis are configured in your environment")
            return

        # Get all registered tasks
        registered_tasks = list(broker.available_tasks.keys())

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

    \b
      example-service tasks run cleanup_temp_files
      example-service tasks run cleanup_temp_files -a max_age_hours=12
      example-service tasks run backup_database --wait
    """
    info(f"Triggering task: {task_name}")

    try:
        from example_service.tasks.broker import broker

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
        for full_name, task in broker.available_tasks.items():
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
                        f"Task may still be running. Check with: example-service tasks status {task_handle.task_id}"
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
        from example_service.tasks.broker import broker

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
        from example_service.tasks.broker import broker

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
        "example_service.tasks.broker:broker",
        "-w",
        str(concurrency),
    ]

    if queue:
        cmd.extend(["--queue", queue])

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        info("Worker stopped")
    except FileNotFoundError:
        error("taskiq command not found. Install with: pip install taskiq")
        sys.exit(1)
