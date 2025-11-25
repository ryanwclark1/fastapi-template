"""Development workflow commands."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click


@click.group()
def dev() -> None:
    """Development workflow commands.

    Commands to streamline development tasks like linting,
    testing, formatting, and type checking.
    """


@dev.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible")
@click.option("--watch", is_flag=True, help="Watch for changes and re-run")
def lint(fix: bool, watch: bool) -> None:
    """Run code linting with ruff.

    Checks code quality and style issues. Use --fix to automatically
    fix issues where possible.

    Example:

        example-service dev lint

        example-service dev lint --fix
    """
    cmd = ["uv", "run", "ruff", "check", "example_service", "tests"]

    if fix:
        cmd.append("--fix")

    if watch:
        cmd.append("--watch")

    click.echo("🔍 Running linter...")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        click.echo("✅ No linting issues found!")
    else:
        click.echo("❌ Linting issues detected", err=True)
        sys.exit(result.returncode)


@dev.command()
@click.option("--check", is_flag=True, help="Check formatting without modifying files")
def format(check: bool) -> None:
    """Format code with ruff.

    Automatically formats Python code according to project standards.

    Example:

        example-service dev format

        example-service dev format --check
    """
    cmd = ["uv", "run", "ruff", "format"]

    if check:
        cmd.append("--check")

    cmd.extend(["example_service", "tests"])

    click.echo("🎨 Formatting code...")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        if check:
            click.echo("✅ Code is properly formatted!")
        else:
            click.echo("✅ Code formatted successfully!")
    else:
        click.echo("❌ Formatting issues detected", err=True)
        sys.exit(result.returncode)


@dev.command()
@click.option("--strict", is_flag=True, help="Run type checking in strict mode")
def typecheck(strict: bool) -> None:
    """Run type checking with mypy.

    Performs static type analysis to catch type-related bugs.

    Example:

        example-service dev typecheck

        example-service dev typecheck --strict
    """
    cmd = ["uv", "run", "mypy", "example_service"]

    if strict:
        cmd.append("--strict")

    click.echo("🔬 Running type checker...")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        click.echo("✅ No type errors found!")
    else:
        click.echo("❌ Type errors detected", err=True)
        sys.exit(result.returncode)


@dev.command()
@click.option("--coverage", is_flag=True, help="Generate coverage report")
@click.option("--html", is_flag=True, help="Generate HTML coverage report")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--mark", "-m", help="Run tests matching given mark expression")
@click.option("--keyword", "-k", help="Run tests matching given keyword expression")
@click.option("--failfast", "-x", is_flag=True, help="Stop on first failure")
@click.argument("path", required=False)
def test(
    coverage: bool,
    html: bool,
    verbose: bool,
    mark: str | None,
    keyword: str | None,
    failfast: bool,
    path: str | None,
) -> None:
    """Run tests with pytest.

    Runs the test suite with optional coverage analysis and filtering.

    Example:

        example-service dev test

        example-service dev test --coverage

        example-service dev test --mark unit

        example-service dev test tests/test_api/

        example-service dev test -k "test_user" --failfast
    """
    cmd = ["uv", "run", "pytest"]

    if coverage:
        cmd.extend(["--cov=example_service", "--cov-report=term-missing"])

    if html:
        cmd.append("--cov-report=html")

    if verbose:
        cmd.append("-v")

    if mark:
        cmd.extend(["-m", mark])

    if keyword:
        cmd.extend(["-k", keyword])

    if failfast:
        cmd.append("-x")

    if path:
        cmd.append(path)
    else:
        cmd.append("tests/")

    click.echo("🧪 Running tests...")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        click.echo("✅ All tests passed!")
    else:
        click.echo("❌ Some tests failed", err=True)
        sys.exit(result.returncode)


@dev.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues")
def quality(fix: bool) -> None:
    """Run all quality checks (lint, format, typecheck, test).

    Runs the complete suite of quality checks in sequence.
    Use before committing code.

    Example:

        example-service dev quality

        example-service dev quality --fix
    """
    checks = [
        ("🔍 Linting", ["lint", "--fix"] if fix else ["lint"]),
        ("🎨 Formatting", ["format"] if fix else ["format", "--check"]),
        ("🔬 Type checking", ["typecheck"]),
        ("🧪 Testing", ["test"]),
    ]

    failed_checks = []

    for name, cmd in checks:
        click.echo(f"\n{name}...")
        click.echo("=" * 60)

        # Run dev subcommand
        result = subprocess.run(
            ["example-service", "dev"] + cmd,
            capture_output=False,
        )

        if result.returncode != 0:
            failed_checks.append(name)
            click.echo(f"❌ {name} failed\n")
        else:
            click.echo(f"✅ {name} passed\n")

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("📊 Quality Check Summary")
    click.echo("=" * 60)

    if not failed_checks:
        click.echo("✅ All checks passed!")
    else:
        click.echo(f"❌ {len(failed_checks)} check(s) failed:")
        for check in failed_checks:
            click.echo(f"  - {check}")
        sys.exit(1)


@dev.command()
@click.option("--port", "-p", default=8000, help="Port to run on")
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to")
@click.option("--reload/--no-reload", default=True, help="Enable auto-reload")
@click.option("--workers", "-w", default=1, help="Number of worker processes")
def serve(port: int, host: str, reload: bool, workers: int) -> None:
    """Run development server with hot-reload.

    Starts a Uvicorn server with automatic reloading for development.

    Example:

        example-service dev serve

        example-service dev serve --port 8080 --host 0.0.0.0

        example-service dev serve --workers 4 --no-reload
    """
    cmd = [
        "uv",
        "run",
        "uvicorn",
        "example_service.app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if reload:
        cmd.append("--reload")

    if workers > 1 and not reload:
        cmd.extend(["--workers", str(workers)])
    elif workers > 1 and reload:
        click.echo("⚠️  Warning: --reload cannot be used with multiple workers", err=True)
        click.echo("    Running with single worker")

    click.echo(f"🚀 Starting development server at http://{host}:{port}")
    click.echo("📝 Press Ctrl+C to stop\n")

    subprocess.run(cmd)


@dev.command()
def clean() -> None:
    """Clean build artifacts and caches.

    Removes Python cache files, build artifacts, and test outputs.

    Example:

        example-service dev clean
    """
    patterns = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.pyd",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".coverage",
        "*.egg-info",
        "dist",
        "build",
    ]

    click.echo("🧹 Cleaning build artifacts and caches...")

    removed_count = 0

    for pattern in patterns:
        for path in Path(".").glob(pattern):
            if path.is_file():
                path.unlink()
                removed_count += 1
                click.echo(f"  Removed: {path}")
            elif path.is_dir():
                import shutil

                shutil.rmtree(path)
                removed_count += 1
                click.echo(f"  Removed: {path}/")

    if removed_count == 0:
        click.echo("✅ No artifacts to clean")
    else:
        click.echo(f"✅ Cleaned {removed_count} artifact(s)")


@dev.command()
def deps() -> None:
    """Check dependency status and updates.

    Shows information about installed dependencies and available updates.

    Example:

        example-service dev deps
    """
    click.echo("📦 Checking dependencies...\n")

    # Show installed packages
    click.echo("Installed packages:")
    subprocess.run(["uv", "pip", "list"])

    click.echo("\n" + "=" * 60)

    # Check for outdated packages
    click.echo("\nOutdated packages:")
    subprocess.run(["uv", "pip", "list", "--outdated"])


@dev.command()
@click.option("--all", "show_all", is_flag=True, help="Show all environment info")
def info(show_all: bool) -> None:
    """Show development environment information.

    Displays Python version, dependencies, and environment status.

    Example:

        example-service dev info

        example-service dev info --all
    """
    click.echo("🔧 Development Environment Information")
    click.echo("=" * 60)

    # Python version
    click.echo(f"\nPython: {sys.version}")

    # Project info
    try:
        import example_service

        click.echo("Project: example-service (version: 0.1.0)")
    except ImportError:
        click.echo("Project: example-service (not installed)")

    if show_all:
        # UV version
        click.echo("\nUV Version:")
        subprocess.run(["uv", "--version"])

        # Environment variables
        import os

        click.echo("\nEnvironment Variables:")
        env_vars = [
            "ENVIRONMENT",
            "APP_DEBUG",
            "DATABASE_URL",
            "REDIS_URL",
            "LOG_LEVEL",
        ]
        for var in env_vars:
            value = os.getenv(var, "not set")
            if "URL" in var or "SECRET" in var or "KEY" in var:
                # Mask sensitive values
                if value != "not set":
                    value = "***" + value[-4:] if len(value) > 4 else "***"
            click.echo(f"  {var}: {value}")


@dev.command()
@click.argument("command", nargs=-1, required=True)
def run(command: tuple[str, ...]) -> None:
    """Run arbitrary command in the project environment.

    Executes any command within the UV virtual environment.

    Example:

        example-service dev run python --version

        example-service dev run alembic current

        example-service dev run pytest -v tests/test_api/
    """
    cmd = ["uv", "run"] + list(command)

    click.echo(f"🏃 Running: {' '.join(command)}\n")
    result = subprocess.run(cmd)

    sys.exit(result.returncode)
