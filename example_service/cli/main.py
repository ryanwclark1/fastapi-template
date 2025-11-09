"""Main CLI entry point using Click."""
from __future__ import annotations

import sys

import click

from example_service.cli.commands.db import db
from example_service.cli.commands.run import run
from example_service.cli.commands.utils import utils


@click.group()
@click.version_option(version="1.0.0", prog_name="example-service")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Example Service CLI.

    Manage the FastAPI service with commands for running servers,
    workers, database migrations, and utility functions.

    Examples:
        \b
        # Run development server
        example-service run server --reload

        # Run worker
        example-service run worker

        # Create database tables
        example-service db init

        # Show service info
        example-service utils info
    """
    ctx.ensure_object(dict)


# Register command groups
cli.add_command(run)
cli.add_command(db)
cli.add_command(utils)


def main() -> None:
    """Main entry point for CLI."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"\n\nError: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
