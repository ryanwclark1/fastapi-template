"""Utility CLI commands."""
from __future__ import annotations

import asyncio
import json

import click


@click.group()
def utils() -> None:
    """Utility commands."""
    pass


@utils.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format",
)
def info(output_format: str) -> None:
    """Show service information.

    Example:
        \b
        example-service utils info
        example-service utils info --format json
    """
    from example_service.core.settings import (
        get_app_settings,
        get_auth_settings,
        get_db_settings,
        get_logging_settings,
        get_otel_settings,
        get_rabbit_settings,
        get_redis_settings,
    )

    app_settings = get_app_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    rabbit_settings = get_rabbit_settings()
    auth_settings = get_auth_settings()
    log_settings = get_logging_settings()
    otel_settings = get_otel_settings()

    info_data = {
        "service": {
            "name": app_settings.service_name,
            "title": app_settings.title,
            "version": app_settings.version,
            "environment": app_settings.environment,
            "debug": app_settings.debug,
        },
        "configuration": {
            "database": db_settings.is_configured,
            "redis": redis_settings.is_configured,
            "rabbitmq": rabbit_settings.is_configured,
            "auth_service": auth_settings.is_configured,
            "tracing": otel_settings.is_configured,
        },
        "logging": {
            "level": log_settings.level,
            "json_format": log_settings.json_format,
            "file": log_settings.log_file,
        },
    }

    if output_format == "json":
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo("\n📋 Service Information")
        click.echo("=" * 60)
        click.echo(f"\nService Name: {info_data['service']['name']}")
        click.echo(f"Title:        {info_data['service']['title']}")
        click.echo(f"Version:      {info_data['service']['version']}")
        click.echo(f"Environment:  {info_data['service']['environment']}")
        click.echo(f"Debug Mode:   {info_data['service']['debug']}")

        click.echo("\n🔧 Configuration Status")
        click.echo("=" * 60)
        for key, value in info_data["configuration"].items():
            status = "✓" if value else "✗"
            click.echo(f"{status} {key.replace('_', ' ').title()}: {value}")

        click.echo("\n📝 Logging Configuration")
        click.echo("=" * 60)
        click.echo(f"Level:       {info_data['logging']['level']}")
        click.echo(f"JSON Format: {info_data['logging']['json_format']}")
        click.echo(f"Log File:    {info_data['logging']['file']}")
        click.echo()


@utils.command()
@click.option(
    "--url",
    default="http://localhost:8000",
    show_default=True,
    help="Service URL to check",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format",
)
def health(url: str, output_format: str) -> None:
    """Check service health via HTTP.

    Makes a request to the health endpoint and displays the result.

    Example:
        \b
        example-service utils health
        example-service utils health --url http://localhost:8080
        example-service utils health --format json
    """
    import httpx

    health_url = f"{url.rstrip('/')}/api/v1/health/"

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(health_url)
            data = response.json()

            if output_format == "json":
                click.echo(json.dumps(data, indent=2))
            else:
                status = data.get("status", "unknown")
                status_emoji = "✓" if status == "healthy" else "✗"

                click.echo(f"\n{status_emoji} Service Health Check")
                click.echo("=" * 60)
                click.echo(f"Status:    {status}")
                click.echo(f"Service:   {data.get('service', 'unknown')}")
                click.echo(f"Version:   {data.get('version', 'unknown')}")
                click.echo(f"Timestamp: {data.get('timestamp', 'unknown')}")

                if "checks" in data:
                    click.echo("\nDependency Checks:")
                    for name, status in data["checks"].items():
                        check_emoji = "✓" if status else "✗"
                        click.echo(f"  {check_emoji} {name}: {status}")

                click.echo()

                # Exit with error code if unhealthy
                if status != "healthy":
                    raise click.Abort()

    except httpx.ConnectError:
        click.echo(f"❌ Failed to connect to {health_url}", err=True)
        click.echo("   Is the service running?", err=True)
        raise click.Abort()
    except httpx.TimeoutException:
        click.echo(f"❌ Request timeout to {health_url}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ Health check failed: {e}", err=True)
        raise click.Abort()


@utils.command()
def routes() -> None:
    """List all registered API routes.

    Example:
        example-service utils routes
    """
    from example_service.app.main import create_app

    app = create_app()

    click.echo("\n📍 Registered Routes")
    click.echo("=" * 80)

    routes_data = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            routes_data.append((methods, route.path, route.name))

    # Sort by path
    routes_data.sort(key=lambda x: x[1])

    # Print in columns
    for methods, path, name in routes_data:
        click.echo(f"{methods:10} {path:40} {name}")

    click.echo(f"\nTotal routes: {len(routes_data)}")
    click.echo()


@utils.command()
def config() -> None:
    """Show current configuration (environment variables).

    Displays all configuration settings (with secrets masked).

    Example:
        example-service utils config
    """
    from example_service.core.settings import (
        get_app_settings,
        get_auth_settings,
        get_db_settings,
        get_logging_settings,
        get_otel_settings,
        get_rabbit_settings,
        get_redis_settings,
    )

    click.echo("\n⚙️  Configuration Settings")
    click.echo("=" * 80)

    # App settings
    click.echo("\n[APP]")
    app_settings = get_app_settings()
    for field in app_settings.model_fields:
        value = getattr(app_settings, field)
        click.echo(f"  {field}: {value}")

    # Database settings
    click.echo("\n[DATABASE]")
    db_settings = get_db_settings()
    click.echo(f"  configured: {db_settings.is_configured}")
    if db_settings.is_configured:
        # Mask password in URL
        url = str(db_settings.database_url)
        if "@" in url:
            url = url.split("@")[0].split("://")[0] + "://***:***@" + url.split("@")[1]
        click.echo(f"  url: {url}")

    # Redis settings
    click.echo("\n[REDIS]")
    redis_settings = get_redis_settings()
    click.echo(f"  configured: {redis_settings.is_configured}")

    # RabbitMQ settings
    click.echo("\n[RABBITMQ]")
    rabbit_settings = get_rabbit_settings()
    click.echo(f"  configured: {rabbit_settings.is_configured}")

    # Auth settings
    click.echo("\n[AUTH]")
    auth_settings = get_auth_settings()
    click.echo(f"  configured: {auth_settings.is_configured}")

    # Logging settings
    click.echo("\n[LOGGING]")
    log_settings = get_logging_settings()
    click.echo(f"  level: {log_settings.level}")
    click.echo(f"  json_format: {log_settings.json_format}")

    # OpenTelemetry settings
    click.echo("\n[OPENTELEMETRY]")
    otel_settings = get_otel_settings()
    click.echo(f"  configured: {otel_settings.is_configured}")

    click.echo()
