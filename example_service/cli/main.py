"""Main CLI entry point for example-service management commands."""

import click

from example_service.cli.commands import (
    cache,
    config,
    data,
    database,
    dev,
    generate,
    monitor,
    scheduler,
    search,
    server,
    storage,
    tasks,
    users,
    utils,
)
from example_service.infra.logging.config import setup_logging


@click.group()
@click.version_option(version="0.1.0", prog_name="example-service")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Example Service CLI - Management commands for FastAPI microservice.

    This CLI provides commands for managing the service infrastructure including
    database operations, cache management, server running, configuration validation,
    background tasks, scheduled jobs, user management, and various utility operations.

    \b
    Command Groups:
      db         Database migrations and management
      cache      Redis cache operations
      search     Full-text search management
      storage    S3-compatible object storage management
      server     Development and production servers
      config     Configuration management
      tasks      Background task management
      scheduler  Scheduled job management
      users      User account management
      data       Data import/export operations
      monitor    Monitoring and observability
      generate   Code generation and scaffolding
      dev        Development workflow commands

    \b
    Quick Start:
      example-service db init           # Test database connection
      example-service db upgrade        # Apply migrations
      example-service config validate   # Check all dependencies
      example-service health-check      # Check service health
      example-service generate resource Product --all  # Generate CRUD resource
      example-service dev quality       # Run all quality checks
    """
    ctx.ensure_object(dict)


# Register command groups - Core infrastructure
cli.add_command(database.db)
cli.add_command(cache.cache)
cli.add_command(search.search)
cli.add_command(storage.storage)
cli.add_command(server.server)
cli.add_command(config.config)

# Register command groups - Task management
cli.add_command(tasks.tasks)
cli.add_command(scheduler.scheduler)

# Register command groups - User and data management
cli.add_command(users.users)
cli.add_command(data.data)

# Register command groups - Monitoring
cli.add_command(monitor.monitor)

# Register command groups - Development tools
cli.add_command(generate.generate)
cli.add_command(dev.dev)

# Register standalone utility commands
cli.add_command(utils.shell)
cli.add_command(utils.health_check)
cli.add_command(utils.export_openapi)


def main() -> None:
    """Entry point for CLI."""
    setup_logging()
    cli(obj={})


if __name__ == "__main__":
    main()
