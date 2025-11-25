"""Server management commands."""

import subprocess
import sys

import click

from example_service.cli.utils import error, info, success, warning
from example_service.core.settings import get_app_settings


@click.group(name="server")
def server() -> None:
    """Server management commands."""


@server.command()
@click.option(
    "--host",
    default=None,
    help="Host to bind (default: from settings or 0.0.0.0)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port to bind (default: from settings or 8000)",
)
@click.option(
    "--reload/--no-reload",
    default=True,
    help="Enable auto-reload on code changes",
)
@click.option(
    "--workers",
    default=1,
    type=int,
    help="Number of worker processes (disable with --reload)",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
    help="Log level",
)
def dev(
    host: str | None,
    port: int | None,
    reload: bool,
    workers: int,
    log_level: str,
) -> None:
    """Run development server with auto-reload."""
    info("Starting development server...")

    # Get settings for defaults
    settings = get_app_settings()
    host = host or settings.app.host
    port = port or settings.app.port

    if reload and workers > 1:
        warning("--reload is incompatible with --workers > 1. Setting workers to 1.")
        workers = 1

    info(f"Server will run at: http://{host}:{port}")
    info(f"Environment: {settings.app.environment}")
    info(f"Auto-reload: {'enabled' if reload else 'disabled'}")

    try:
        cmd = [
            "uvicorn",
            "example_service.app.main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            log_level,
        ]

        if reload:
            cmd.append("--reload")
        else:
            cmd.extend(["--workers", str(workers)])

        success("Starting uvicorn...")
        subprocess.run(cmd)

    except KeyboardInterrupt:
        info("\nShutting down server...")
    except Exception as e:
        error(f"Failed to start server: {e}")
        sys.exit(1)


@server.command()
@click.option(
    "--host",
    default=None,
    help="Host to bind (default: from settings)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port to bind (default: from settings)",
)
@click.option(
    "--workers",
    default=4,
    type=int,
    help="Number of worker processes",
)
@click.option(
    "--access-log/--no-access-log",
    default=True,
    help="Enable access logging",
)
def prod(
    host: str | None,
    port: int | None,
    workers: int,
    access_log: bool,
) -> None:
    """Run production server (no auto-reload, multiple workers)."""
    info("Starting production server...")

    # Get settings for defaults
    settings = get_app_settings()
    host = host or settings.app.host
    port = port or settings.app.port

    info(f"Server will run at: http://{host}:{port}")
    info(f"Environment: {settings.app.environment}")
    info(f"Workers: {workers}")
    info(f"Access log: {'enabled' if access_log else 'disabled'}")

    try:
        cmd = [
            "uvicorn",
            "example_service.app.main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--workers",
            str(workers),
            "--log-level",
            "info",
        ]

        if not access_log:
            cmd.append("--no-access-log")

        success("Starting uvicorn in production mode...")
        subprocess.run(cmd)

    except KeyboardInterrupt:
        info("\nShutting down server...")
    except Exception as e:
        error(f"Failed to start server: {e}")
        sys.exit(1)


@server.command()
@click.option(
    "--queue",
    default="default",
    help="Queue name to consume from",
)
@click.option(
    "--concurrency",
    default=4,
    type=int,
    help="Number of concurrent workers",
)
def worker(queue: str, concurrency: int) -> None:
    """Run Taskiq background task worker."""
    info(f"Starting task worker for queue: {queue}")
    info(f"Concurrency: {concurrency}")

    warning("⚠ Worker command needs to be configured for your specific Taskiq setup")
    info("To implement: Configure your Taskiq broker and worker startup")
    info("Example: taskiq worker example_service.workers.broker:broker")

    # Example implementation:
    # try:
    #     cmd = [
    #         "taskiq",
    #         "worker",
    #         "example_service.workers.broker:broker",
    #         "--max-async-tasks",
    #         str(concurrency),
    #     ]
    #     subprocess.run(cmd)
    # except KeyboardInterrupt:
    #     info("\nShutting down worker...")
    # except Exception as e:
    #     error(f"Failed to start worker: {e}")
    #     sys.exit(1)


@server.command()
@click.option(
    "--queue",
    default="default",
    help="Queue name to consume from",
)
def broker(queue: str) -> None:
    """Run FastStream RabbitMQ message broker consumer."""
    info(f"Starting message broker consumer for queue: {queue}")

    warning("⚠ Broker command needs to be configured for your specific FastStream setup")
    info("To implement: Configure your FastStream broker and consumer startup")
    info("Example: faststream run example_service.workers.broker:broker")

    # Example implementation:
    # try:
    #     cmd = [
    #         "faststream",
    #         "run",
    #         "example_service.workers.broker:broker",
    #     ]
    #     subprocess.run(cmd)
    # except KeyboardInterrupt:
    #     info("\nShutting down broker...")
    # except Exception as e:
    #     error(f"Failed to start broker: {e}")
    #     sys.exit(1)
