"""Run commands for server and workers."""
from __future__ import annotations

import click


@click.group()
def run() -> None:
    """Run services (server, worker, etc.)."""
    pass


@run.command()
@click.option(
    "--host",
    default="0.0.0.0",
    show_default=True,
    help="Bind host",
)
@click.option(
    "--port",
    default=8000,
    show_default=True,
    type=int,
    help="Bind port",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development",
)
@click.option(
    "--workers",
    default=1,
    show_default=True,
    type=int,
    help="Number of worker processes",
)
@click.option(
    "--log-level",
    default="info",
    show_default=True,
    type=click.Choice(["debug", "info", "warning", "error", "critical"], case_sensitive=False),
    help="Log level",
)
def server(
    host: str,
    port: int,
    reload: bool,
    workers: int,
    log_level: str,
) -> None:
    """Run FastAPI server with Uvicorn.

    Examples:
        \b
        # Development server with auto-reload
        example-service run server --reload

        # Production server with 4 workers
        example-service run server --workers 4

        # Custom host and port
        example-service run server --host 127.0.0.1 --port 8080
    """
    import uvicorn

    click.echo(f"Starting server on {host}:{port}")
    click.echo(f"Workers: {workers}")
    click.echo(f"Reload: {reload}")
    click.echo(f"Log level: {log_level}")
    click.echo()

    # Disable workers when reload is enabled
    if reload and workers > 1:
        click.echo("⚠️  Disabling multiple workers in reload mode", err=True)
        workers = 1

    uvicorn.run(
        "example_service.app.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level=log_level.lower(),
        access_log=True,
    )


@run.command()
@click.option(
    "--queues",
    default="default",
    show_default=True,
    help="Comma-separated list of queues to consume",
)
@click.option(
    "--concurrency",
    default=4,
    show_default=True,
    type=int,
    help="Number of concurrent tasks",
)
def worker(queues: str, concurrency: int) -> None:
    """Run background task worker.

    Consumes tasks from RabbitMQ queues using Taskiq.

    Examples:
        \b
        # Run worker for default queue
        example-service run worker

        # Run worker for multiple queues
        example-service run worker --queues default,priority

        # Run with custom concurrency
        example-service run worker --concurrency 8
    """
    click.echo("Starting background task worker")
    click.echo(f"Queues: {queues}")
    click.echo(f"Concurrency: {concurrency}")
    click.echo()

    queue_list = [q.strip() for q in queues.split(",")]

    try:
        import asyncio

        from example_service.infra.tasks.broker import get_taskiq_broker

        async def run_worker() -> None:
            """Run the Taskiq worker."""
            broker = get_taskiq_broker()
            click.echo("Worker started. Press Ctrl+C to stop.")
            click.echo()

            # In production, this would run the actual broker
            # For now, just demonstrate the structure
            await broker.startup()
            try:
                # Worker loop would go here
                # await broker.listen()
                click.echo("Worker is running (demo mode)")
                # Keep running until interrupted
                await asyncio.Future()
            finally:
                await broker.shutdown()

        asyncio.run(run_worker())

    except ImportError:
        click.echo("❌ Taskiq not configured or RabbitMQ not available", err=True)
        click.echo("   Configure RABBIT_RABBITMQ_URL in environment", err=True)
        raise click.Abort()
    except KeyboardInterrupt:
        click.echo("\n\nWorker stopped")


@run.command()
@click.option(
    "--host",
    default="0.0.0.0",
    show_default=True,
    help="Bind host",
)
@click.option(
    "--port",
    default=8000,
    show_default=True,
    type=int,
    help="Bind port",
)
def dev(host: str, port: int) -> None:
    """Run development server with optimal settings.

    Convenience command that enables auto-reload and debug mode.

    Example:
        example-service run dev
    """
    import uvicorn

    click.echo("🚀 Starting development server")
    click.echo(f"   URL: http://{host}:{port}")
    click.echo(f"   Docs: http://{host}:{port}/docs")
    click.echo(f"   Auto-reload: enabled")
    click.echo()

    uvicorn.run(
        "example_service.app.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=True,
        log_level="debug",
        access_log=True,
    )
