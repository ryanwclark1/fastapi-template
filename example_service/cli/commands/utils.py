"""Utility commands."""

import json
import sys

import click
import httpx

from example_service.cli.utils import coro, error, info, section, success, warning
from example_service.core.settings import get_app_settings
from example_service.core.settings.unified import get_settings


@click.command()
def shell() -> None:
    """Open an interactive Python shell with app context loaded."""
    info("Starting interactive shell with app context...")

    try:
        # Import commonly used modules
        import asyncio

        from example_service.app.main import app
        from example_service.infra.cache import get_redis
        from example_service.infra.database import get_session

        # Setup banner
        banner = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    Example Service - Interactive Shell                     ║
╚════════════════════════════════════════════════════════════════════════════╝

Available imports:
  • app            - FastAPI application instance
  • get_settings   - Settings loader
  • get_session    - Database session context manager
  • get_redis      - Redis client getter
  • asyncio        - Async runtime

Example usage:
  settings = get_app_settings()
  print(settings.app.service_name)

  async with get_session() as session:
      result = await session.execute(text("SELECT 1"))
      print(result.scalar())

Use 'exit()' or Ctrl+D to exit the shell.
"""

        # Try IPython first (better experience)
        try:
            from IPython import embed

            embed(
                banner1=banner,
                user_ns={
                    "app": app,
                    "get_settings": get_settings,
                    "get_session": get_session,
                    "get_redis": get_redis,
                    "asyncio": asyncio,
                },
            )
        except ImportError:
            # Fall back to standard Python shell
            import code

            click.echo(banner)
            code.interact(
                local={
                    "app": app,
                    "get_settings": get_settings,
                    "get_session": get_session,
                    "get_redis": get_redis,
                    "asyncio": asyncio,
                }
            )

    except Exception as e:
        error(f"Failed to start shell: {e}")
        sys.exit(1)


@click.command(name="health-check")
@coro
async def health_check() -> None:
    """Run comprehensive health check on all service dependencies."""
    section("SERVICE HEALTH CHECK")

    all_healthy = True

    # Check database
    click.echo("\n🗄️  Database (PostgreSQL):")
    try:
        from sqlalchemy import text

        from example_service.infra.database import get_session

        async with get_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            success("  ✓ Database connection successful")
            info(f"  Version: {version.split(',')[0]}")
    except Exception as e:
        error(f"  ✗ Database check failed: {e}")
        all_healthy = False

    # Check Redis cache
    click.echo("\n🔄 Cache (Redis):")
    try:
        from example_service.infra.cache import get_redis

        redis = await get_redis()
        pong = await redis.ping()
        if pong:
            success("  ✓ Redis connection successful")

            # Get basic info
            info_dict = await redis.info("server")
            info(f"  Version: {info_dict.get('redis_version')}")

        await redis.aclose()
    except Exception as e:
        error(f"  ✗ Redis check failed: {e}")
        all_healthy = False

    # Check RabbitMQ (if accessible)
    click.echo("\n📨 Message Broker (RabbitMQ):")
    try:
        settings = get_app_settings()

        # Try to connect using httpx to management API (if available)
        # This is a basic check - in production you'd use pika or similar
        info("  RabbitMQ URL configured")
        warning("  ⚠ Full connectivity check not implemented")
        info("  Implement with: import pika; connection = pika.BlockingConnection(...)")

    except Exception as e:
        warning(f"  ⚠ RabbitMQ check skipped: {e}")

    # Check API endpoints
    click.echo("\n🌐 API Endpoints:")
    try:
        settings = get_app_settings()
        base_url = f"http://{settings.app.host}:{settings.app.port}"

        async with httpx.AsyncClient() as client:
            # Check liveness
            response = await client.get(f"{base_url}{settings.app.api_prefix}/health/live")
            if response.status_code == 200:
                success(f"  ✓ Liveness endpoint: {response.status_code}")
            else:
                error(f"  ✗ Liveness endpoint failed: {response.status_code}")
                all_healthy = False

            # Check readiness
            response = await client.get(f"{base_url}{settings.app.api_prefix}/health/ready")
            if response.status_code == 200:
                success(f"  ✓ Readiness endpoint: {response.status_code}")
            else:
                warning(f"  ⚠ Readiness endpoint: {response.status_code}")

    except httpx.ConnectError:
        warning("  ⚠ API server not running (this is OK if you haven't started it)")
    except Exception as e:
        error(f"  ✗ API endpoint check failed: {e}")

    # Configuration validation
    click.echo("\n⚙️  Configuration:")
    try:
        settings = get_app_settings()
        success("  ✓ Settings loaded successfully")
        info(f"  Environment: {settings.app.environment}")
        info(f"  Service: {settings.app.service_name}")
    except Exception as e:
        error(f"  ✗ Configuration check failed: {e}")
        all_healthy = False

    # Summary
    click.echo("\n" + "=" * 80)
    if all_healthy:
        success("✅ All critical health checks passed!")
    else:
        error("❌ Some health checks failed. Review the output above.")
        sys.exit(1)


@click.command(name="export-openapi")
@click.option(
    "--output",
    "-o",
    default="openapi.json",
    help="Output file path",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml"]),
    default="json",
    help="Output format",
)
def export_openapi(output: str, output_format: str) -> None:
    """Export OpenAPI schema to a file."""
    info("Exporting OpenAPI schema...")

    try:
        from example_service.app.main import app

        # Get OpenAPI schema
        openapi_schema = app.openapi()

        # Write to file
        if output_format == "json":
            with open(output, "w") as f:
                json.dump(openapi_schema, f, indent=2)
        else:  # yaml
            try:
                import yaml

                with open(output, "w") as f:
                    yaml.dump(openapi_schema, f, default_flow_style=False)
            except ImportError:
                error("PyYAML is not installed. Install with: pip install pyyaml")
                sys.exit(1)

        success(f"OpenAPI schema exported to: {output}")
        info(f"Format: {output_format.upper()}")

        # Show some stats
        info(f"Title: {openapi_schema.get('info', {}).get('title')}")
        info(f"Version: {openapi_schema.get('info', {}).get('version')}")
        paths_count = len(openapi_schema.get("paths", {}))
        info(f"Endpoints: {paths_count}")

    except Exception as e:
        error(f"Failed to export OpenAPI schema: {e}")
        sys.exit(1)
