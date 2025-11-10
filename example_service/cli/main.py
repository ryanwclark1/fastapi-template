"""Main CLI entry point for example-service management commands."""

import click

from example_service.cli.commands import cache, config, database, server, utils


@click.group()
@click.version_option(version="0.1.0", prog_name="example-service")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """
    Example Service CLI - Management commands for FastAPI microservice.

    This CLI provides commands for managing the service infrastructure including
    database operations, cache management, server running, configuration validation,
    and various utility operations.
    """
    ctx.ensure_object(dict)


# Register command groups
cli.add_command(database.db)
cli.add_command(cache.cache)
cli.add_command(server.server)
cli.add_command(config.config)

# Register standalone utility commands
cli.add_command(utils.shell)
cli.add_command(utils.health_check)
cli.add_command(utils.export_openapi)


def main() -> None:
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
