"""Output formatting utilities for CLI commands."""

import click


def success(message: str) -> None:
    """Print a success message in green."""
    click.secho(f"✓ {message}", fg="green")


def error(message: str) -> None:
    """Print an error message in red."""
    click.secho(f"✗ {message}", fg="red", err=True)


def warning(message: str) -> None:
    """Print a warning message in yellow."""
    click.secho(f"⚠ {message}", fg="yellow")


def info(message: str) -> None:
    """Print an info message in blue."""
    click.secho(f"ℹ {message}", fg="blue")


def header(message: str) -> None:
    """Print a header message in cyan bold."""
    click.secho(f"\n{message}", fg="cyan", bold=True)


def section(title: str) -> None:
    """Print a section divider."""
    click.secho(f"\n{'=' * 60}", fg="white", dim=True)
    click.secho(title, fg="white", bold=True)
    click.secho('=' * 60, fg="white", dim=True)
