"""Configuration management commands."""

import json
import sys
from pathlib import Path

import click

from example_service.cli.utils import error, info, success, warning
from example_service.core.settings import get_settings


@click.group(name="config")
def config() -> None:
    """Configuration management commands."""


@config.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml", "table"]),
    default="table",
    help="Output format",
)
@click.option(
    "--show-secrets/--hide-secrets",
    default=False,
    help="Show sensitive values (passwords, tokens)",
)
def show(output_format: str, show_secrets: bool) -> None:
    """Display current configuration settings."""
    info("Loading configuration...")

    try:
        settings = get_settings()

        if not show_secrets:
            warning("⚠ Secrets are hidden. Use --show-secrets to display them.")

        # Build config dict
        config_dict = {
            "app": {
                "name": settings.app.service_name,
                "environment": settings.app.environment,
                "debug": settings.app.debug,
                "host": settings.app.host,
                "port": settings.app.port,
                "api_prefix": settings.app.api_v1_str,
            },
            "database": {
                "host": settings.database.db_host,
                "port": settings.database.db_port,
                "name": settings.database.db_name,
                "user": settings.database.db_user,
                "password": "***" if not show_secrets else settings.database.db_password.get_secret_value(),
                "pool_size": settings.database.db_pool_size,
                "max_overflow": settings.database.db_max_overflow,
            },
            "cache": {
                "url": settings.cache.redis_url if show_secrets else "***",
                "key_prefix": settings.cache.redis_key_prefix,
                "ttl": settings.cache.redis_ttl,
                "max_connections": settings.cache.redis_max_connections,
            },
            "messaging": {
                "url": settings.messaging.rabbit_url if show_secrets else "***",
                "queue_name": settings.messaging.rabbit_queue_name,
                "exchange": settings.messaging.rabbit_exchange,
                "max_consumers": settings.messaging.rabbit_max_consumers,
            },
            "auth": {
                "secret_key": "***" if not show_secrets else settings.auth.secret_key.get_secret_value(),
                "algorithm": settings.auth.algorithm,
                "access_token_expire_minutes": settings.auth.access_token_expire_minutes,
            },
            "logging": {
                "level": settings.logging.log_level,
                "format": settings.logging.log_format,
                "json_logs": settings.logging.json_logs,
            },
            "observability": {
                "otel_enabled": settings.otel.otel_enabled,
                "otel_service_name": settings.otel.otel_service_name,
                "otel_exporter_endpoint": settings.otel.otel_exporter_otlp_endpoint,
            },
        }

        if output_format == "json":
            click.echo(json.dumps(config_dict, indent=2, default=str))

        elif output_format == "yaml":
            try:
                import yaml

                click.echo(yaml.dump(config_dict, default_flow_style=False))
            except ImportError:
                error("PyYAML is not installed. Install with: pip install pyyaml")
                sys.exit(1)

        else:  # table format
            click.echo("\n" + "=" * 80)
            click.echo("CONFIGURATION SETTINGS")
            click.echo("=" * 80)

            for section, values in config_dict.items():
                click.echo(f"\n[{section.upper()}]")
                for key, value in values.items():
                    click.echo(f"  {key:30} = {value}")

            click.echo("\n" + "=" * 80)

        success("\nConfiguration loaded successfully!")

    except Exception as e:
        error(f"Failed to load configuration: {e}")
        sys.exit(1)


@config.command()
def validate() -> None:
    """Validate configuration and check all dependencies."""
    info("Validating configuration...")

    errors_found = False

    try:
        # Load settings (will raise if invalid)
        settings = get_settings()
        success("✓ Settings loaded successfully")

        # Check database configuration
        click.echo("\n🗄️  Database Configuration:")
        try:
            db_url = settings.database.database_url
            info(f"  Database URL: {settings.database.db_host}:{settings.database.db_port}/{settings.database.db_name}")
            success("  ✓ Database settings valid")
        except Exception as e:
            error(f"  ✗ Database configuration error: {e}")
            errors_found = True

        # Check cache configuration
        click.echo("\n🔄 Cache Configuration:")
        try:
            cache_url = settings.cache.redis_url
            info(f"  Redis URL configured")
            success("  ✓ Cache settings valid")
        except Exception as e:
            error(f"  ✗ Cache configuration error: {e}")
            errors_found = True

        # Check messaging configuration
        click.echo("\n📨 Messaging Configuration:")
        try:
            rabbit_url = settings.messaging.rabbit_url
            info(f"  RabbitMQ URL configured")
            success("  ✓ Messaging settings valid")
        except Exception as e:
            error(f"  ✗ Messaging configuration error: {e}")
            errors_found = True

        # Check auth configuration
        click.echo("\n🔐 Authentication Configuration:")
        try:
            secret_key = settings.auth.secret_key.get_secret_value()
            if len(secret_key) < 32:
                warning(f"  ⚠ Secret key is short ({len(secret_key)} chars). Recommend 32+ chars.")
            else:
                success(f"  ✓ Secret key configured ({len(secret_key)} chars)")
        except Exception as e:
            error(f"  ✗ Auth configuration error: {e}")
            errors_found = True

        # Check logging configuration
        click.echo("\n📝 Logging Configuration:")
        info(f"  Log level: {settings.logging.log_level}")
        info(f"  JSON logs: {settings.logging.json_logs}")
        success("  ✓ Logging settings valid")

        # Check observability configuration
        click.echo("\n📊 Observability Configuration:")
        if settings.otel.otel_enabled:
            info(f"  OpenTelemetry: enabled")
            info(f"  Service name: {settings.otel.otel_service_name}")
            info(f"  Exporter endpoint: {settings.otel.otel_exporter_otlp_endpoint}")
            success("  ✓ Observability configured")
        else:
            info("  OpenTelemetry: disabled")

        # Summary
        click.echo("\n" + "=" * 80)
        if errors_found:
            error("❌ Configuration validation failed with errors")
            sys.exit(1)
        else:
            success("✅ All configuration checks passed!")

    except Exception as e:
        error(f"Failed to validate configuration: {e}")
        sys.exit(1)


@config.command()
@click.option(
    "--output",
    "-o",
    default=".env.example",
    help="Output file path",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Overwrite existing file",
)
def generate_env(output: str, overwrite: bool) -> None:
    """Generate a .env template file with all available settings."""
    output_path = Path(output)

    if output_path.exists() and not overwrite:
        error(f"File {output} already exists. Use --overwrite to replace it.")
        sys.exit(1)

    info(f"Generating environment template: {output}")

    env_template = """# Example Service Environment Configuration
# Copy this file to .env and fill in your values

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================
APP_SERVICE_NAME=example-service
APP_ENVIRONMENT=development
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000
APP_API_V1_STR=/api/v1
APP_CORS_ORIGINS=["http://localhost:3000"]

# ============================================================================
# DATABASE SETTINGS (PostgreSQL)
# ============================================================================
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_secure_password_here
DB_NAME=example_service
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30.0
DB_POOL_RECYCLE=3600
DB_ECHO=false

# ============================================================================
# CACHE SETTINGS (Redis)
# ============================================================================
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=example_service:
REDIS_TTL=3600
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=5.0

# ============================================================================
# MESSAGE BROKER SETTINGS (RabbitMQ)
# ============================================================================
RABBIT_URL=amqp://guest:guest@localhost:5672/
RABBIT_QUEUE_NAME=example_service_queue
RABBIT_EXCHANGE=example_service_exchange
RABBIT_ROUTING_KEY=example_service
RABBIT_MAX_CONSUMERS=10

# ============================================================================
# AUTHENTICATION SETTINGS
# ============================================================================
AUTH_SECRET_KEY=your-secret-key-min-32-characters-long-change-this-in-production
AUTH_ALGORITHM=HS256
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=30

# ============================================================================
# LOGGING SETTINGS
# ============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_JSON_LOGS=true

# ============================================================================
# OPENTELEMETRY SETTINGS
# ============================================================================
OTEL_ENABLED=false
OTEL_SERVICE_NAME=example-service
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_TRACES_SAMPLER=always_on
OTEL_TRACES_EXPORTER=otlp

# ============================================================================
# TESTING OVERRIDES (optional)
# ============================================================================
# TESTING=true
# TEST_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db
"""

    try:
        output_path.write_text(env_template)
        success(f"Environment template created: {output}")
        info("Copy this file to .env and update with your values")

    except Exception as e:
        error(f"Failed to generate environment template: {e}")
        sys.exit(1)


@config.command()
@click.argument("key")
def get(key: str) -> None:
    """Get a specific configuration value by key path (e.g., app.service_name)."""
    try:
        settings = get_settings()

        # Parse key path
        parts = key.split(".")
        value = settings

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            else:
                error(f"Configuration key not found: {key}")
                sys.exit(1)

        # Handle SecretStr
        if hasattr(value, "get_secret_value"):
            warning("This is a secret value. Use 'config show --show-secrets' to view it.")
            click.echo("***")
        else:
            click.echo(value)

    except Exception as e:
        error(f"Failed to get configuration value: {e}")
        sys.exit(1)
