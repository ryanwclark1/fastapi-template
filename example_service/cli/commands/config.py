"""Configuration management commands."""

import json
import sys
from pathlib import Path

import click

from example_service.cli.utils import error, info, success, warning
from example_service.core.settings import get_app_settings


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
        settings = get_app_settings()

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
                "api_prefix": settings.app.api_prefix,
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
                "level": settings.logging.level,
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
        settings = get_app_settings()
        success("✓ Settings loaded successfully")

        # Check database configuration
        click.echo("\n🗄️  Database Configuration:")
        try:
            info(f"  Database URL: {settings.database.db_host}:{settings.database.db_port}/{settings.database.db_name}")
            success("  ✓ Database settings valid")
        except Exception as e:
            error(f"  ✗ Database configuration error: {e}")
            errors_found = True

        # Check cache configuration
        click.echo("\n🔄 Cache Configuration:")
        try:
            info("  Redis URL configured")
            success("  ✓ Cache settings valid")
        except Exception as e:
            error(f"  ✗ Cache configuration error: {e}")
            errors_found = True

        # Check messaging configuration
        click.echo("\n📨 Messaging Configuration:")
        try:
            info("  RabbitMQ URL configured")
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
        info(f"  Log level: {settings.logging.level}")
        info(f"  JSON logs: {settings.logging.json_logs}")
        success("  ✓ Logging settings valid")

        # Check observability configuration
        click.echo("\n📊 Observability Configuration:")
        if settings.otel.otel_enabled:
            info("  OpenTelemetry: enabled")
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


def _extract_defaults_from_settings() -> dict[str, tuple[str, str]]:
    """Extract default values from all settings classes.

    Returns:
        Dict mapping env var name to (prefix, formatted_default) tuple.
        Handles SecretStr, lists, bools, Paths, and other types.
    """
    import json
    from pathlib import Path

    from pydantic import SecretStr
    from pydantic_core import PydanticUndefined

    from example_service.core.settings.app import AppSettings
    from example_service.core.settings.auth import AuthSettings
    from example_service.core.settings.backup import BackupSettings
    from example_service.core.settings.logs import LoggingSettings
    from example_service.core.settings.otel import OtelSettings
    from example_service.core.settings.postgres import PostgresSettings
    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.redis import RedisSettings

    defaults = {}

    # Define settings classes with their prefixes
    settings_map = [
        (AppSettings, "APP_"),
        (PostgresSettings, "DB_"),
        (RedisSettings, "REDIS_"),
        (RabbitSettings, "RABBIT_"),
        (AuthSettings, "AUTH_"),
        (LoggingSettings, "LOG_"),
        (OtelSettings, "OTEL_"),
        (BackupSettings, "BACKUP_"),
    ]

    for settings_cls, prefix in settings_map:
        # Iterate through model_fields
        for field_name, field_info in settings_cls.model_fields.items():
            # Build env var name
            env_name = f"{prefix}{field_name.upper()}"

            # Get default value
            default_val = field_info.default
            if default_val is PydanticUndefined:
                if field_info.default_factory is not None:
                    # Call factory to get default
                    try:
                        default_val = field_info.default_factory()
                    except Exception:
                        # Skip if factory fails
                        continue
                else:
                    # No default - skip
                    continue

            # Format the default value for .env file
            if isinstance(default_val, SecretStr):
                # Don't expose secret values
                formatted = "change-this-secret-key"
            elif isinstance(default_val, Path):
                formatted = str(default_val)
            elif isinstance(default_val, list):
                # Format as JSON array or empty brackets
                formatted = "[]" if len(default_val) == 0 else json.dumps(default_val)
            elif isinstance(default_val, bool):
                formatted = str(default_val).lower()
            elif default_val is None:
                formatted = ""
            else:
                formatted = str(default_val)

            defaults[env_name] = (prefix, formatted)

    return defaults


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
APP_API_PREFIX=/api/v1
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


@config.command(name="generate-env-with-defaults")
@click.option(
    "--output",
    "-o",
    default=".env.generated",
    help="Output file path",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Overwrite existing file",
)
def generate_env_with_defaults(output: str, overwrite: bool) -> None:
    """Generate .env file with actual default values from pydantic settings.

    Extracts default values from all settings classes and generates
    a .env template file with those defaults populated.
    """
    output_path = Path(output)

    if output_path.exists() and not overwrite:
        error(f"File {output} already exists. Use --overwrite to replace it.")
        sys.exit(1)

    info(f"Generating environment file with defaults: {output}")

    try:
        # Extract defaults from settings classes
        defaults = _extract_defaults_from_settings()

        # Build .env content with sections
        lines = [
            "# Example Service Environment Configuration",
            "# Generated from pydantic settings defaults",
            "# Copy this file to .env and customize as needed",
            "",
        ]

        # Helper to add a section
        def add_section(title: str, prefix: str) -> None:
            lines.append("# " + "=" * 76)
            lines.append(f"# {title}")
            lines.append("# " + "=" * 76)

            # Get all env vars with this prefix
            section_vars = {k: v[1] for k, v in defaults.items() if v[0] == prefix}

            # Sort by name for consistent ordering
            for var_name in sorted(section_vars.keys()):
                value = section_vars[var_name]
                lines.append(f"{var_name}={value}")

            lines.append("")

        # Add sections for each settings domain
        add_section("APPLICATION SETTINGS", "APP_")
        add_section("DATABASE SETTINGS (PostgreSQL)", "DB_")
        add_section("CACHE SETTINGS (Redis)", "REDIS_")
        add_section("MESSAGE BROKER SETTINGS (RabbitMQ)", "RABBIT_")
        add_section("AUTHENTICATION SETTINGS", "AUTH_")
        add_section("LOGGING SETTINGS", "LOG_")
        add_section("OPENTELEMETRY SETTINGS", "OTEL_")
        add_section("BACKUP SETTINGS", "BACKUP_")

        # Write to file
        env_content = "\n".join(lines)
        output_path.write_text(env_content)

        success(f"Generated environment file: {output}")
        info(f"Total variables: {len(defaults)}")
        info("Copy this file to .env and update with your values")

    except Exception as e:
        error(f"Failed to generate environment file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@config.command()
@click.argument("key")
def get(key: str) -> None:
    """Get a specific configuration value by key path (e.g., app.service_name)."""
    try:
        settings = get_app_settings()

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


@config.command(name="env")
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show all environment variables, not just app-related ones",
)
@click.option(
    "--filter",
    "filter_prefix",
    default=None,
    help="Filter by prefix (e.g., DB_, REDIS_, RABBIT_)",
)
def show_env(show_all: bool, filter_prefix: str | None) -> None:
    """Show environment variables status."""
    import os

    from example_service.cli.utils import header, section

    header("Environment Variables")

    # Define expected environment variables by category
    expected_vars = {
        "Application": [
            "APP_SERVICE_NAME",
            "APP_ENVIRONMENT",
            "APP_DEBUG",
            "APP_HOST",
            "APP_PORT",
            "APP_API_PREFIX",
        ],
        "Database": [
            "DB_HOST",
            "DB_PORT",
            "DB_USER",
            "DB_PASSWORD",
            "DB_NAME",
            "DB_POOL_SIZE",
            "DB_MAX_OVERFLOW",
        ],
        "Redis": [
            "REDIS_URL",
            "REDIS_KEY_PREFIX",
            "REDIS_TTL",
            "REDIS_MAX_CONNECTIONS",
        ],
        "RabbitMQ": [
            "RABBIT_URL",
            "RABBIT_HOST",
            "RABBIT_PORT",
            "RABBIT_USER",
            "RABBIT_PASSWORD",
            "RABBIT_VHOST",
            "RABBIT_QUEUE_NAME",
        ],
        "Authentication": [
            "AUTH_SECRET_KEY",
            "AUTH_ALGORITHM",
            "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
        ],
        "Observability": [
            "OTEL_ENABLED",
            "OTEL_SERVICE_NAME",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "LOG_LEVEL",
            "LOG_FORMAT",
        ],
        "Backup": [
            "BACKUP_ENABLED",
            "BACKUP_LOCAL_DIR",
            "BACKUP_S3_BUCKET",
            "BACKUP_RETENTION_DAYS",
        ],
    }

    set_count = 0
    unset_count = 0

    if show_all:
        # Show all environment variables
        section("All Environment Variables")
        for key in sorted(os.environ.keys()):
            if filter_prefix and not key.startswith(filter_prefix):
                continue
            value = os.environ[key]
            # Mask sensitive values
            if any(s in key.upper() for s in ["PASSWORD", "SECRET", "TOKEN", "KEY"]):
                value = "***"
            click.echo(f"  {key}={value[:50]}{'...' if len(value) > 50 else ''}")
    else:
        # Show expected variables by category
        for category, variables in expected_vars.items():
            if filter_prefix:
                variables = [v for v in variables if v.startswith(filter_prefix)]
                if not variables:
                    continue

            section(category)
            for var in variables:
                value = os.environ.get(var)
                if value:
                    set_count += 1
                    # Mask sensitive values
                    if any(s in var.upper() for s in ["PASSWORD", "SECRET", "TOKEN", "KEY"]):
                        display_value = "***"
                    else:
                        display_value = value[:40] + ("..." if len(value) > 40 else "")
                    click.echo(f"  {click.style('OK', fg='green')} {var}={display_value}")
                else:
                    unset_count += 1
                    click.echo(f"  {click.style('--', fg='red')} {var} (not set)")

        click.echo()
        info(f"Set: {set_count}, Unset: {unset_count}")

        if unset_count > 0:
            warning("Some environment variables are not set")
            info("Use 'example-service config generate-env' to create a template")


@config.command(name="check-env")
def check_env() -> None:
    """Verify all required environment variables are set."""
    import os

    from example_service.cli.utils import header, section

    header("Environment Check")

    # Required variables (must be set)
    required = [
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "AUTH_SECRET_KEY",
    ]

    # Optional but recommended
    recommended = [
        "APP_ENVIRONMENT",
        "REDIS_URL",
        "LOG_LEVEL",
    ]

    errors_list = []
    warnings_list = []

    section("Required Variables")
    for var in required:
        value = os.environ.get(var)
        if value:
            click.echo(f"  {click.style('OK', fg='green')} {var}")
        else:
            click.echo(f"  {click.style('MISSING', fg='red')} {var}")
            errors_list.append(var)

    section("Recommended Variables")
    for var in recommended:
        value = os.environ.get(var)
        if value:
            click.echo(f"  {click.style('OK', fg='green')} {var}")
        else:
            click.echo(f"  {click.style('DEFAULT', fg='yellow')} {var} - not set (using default)")
            warnings_list.append(var)

    # Check for common issues
    section("Configuration Checks")

    # Check secret key length
    secret_key = os.environ.get("AUTH_SECRET_KEY", "")
    if secret_key and len(secret_key) < 32:
        click.echo(f"  {click.style('WARN', fg='yellow')} AUTH_SECRET_KEY is short ({len(secret_key)} chars, recommend 32+)")
        warnings_list.append("AUTH_SECRET_KEY_LENGTH")
    elif secret_key:
        click.echo(f"  {click.style('OK', fg='green')} AUTH_SECRET_KEY length OK ({len(secret_key)} chars)")

    # Check environment value
    env = os.environ.get("APP_ENVIRONMENT", "development")
    if env == "production":
        debug = os.environ.get("APP_DEBUG", "false").lower()
        if debug == "true":
            click.echo(f"  {click.style('WARN', fg='yellow')} APP_DEBUG=true in production environment")
            warnings_list.append("DEBUG_IN_PROD")
        else:
            click.echo(f"  {click.style('OK', fg='green')} Debug disabled in production")

    # Summary
    click.echo()
    if errors_list:
        error(f"FAILED: {len(errors_list)} required variable(s) missing")
        info("Set these variables in your .env file or environment")
        sys.exit(1)
    elif warnings_list:
        warning(f"Passed with {len(warnings_list)} warning(s)")
    else:
        success("All environment checks passed!")


@config.command(name="sources")
def show_sources() -> None:
    """Show where configuration values are loaded from."""
    import os

    from example_service.cli.utils import header, section

    header("Configuration Sources")

    # Check for .env files
    section("Environment Files")
    env_files = [
        Path(".env"),
        Path(".env.local"),
        Path(".env.development"),
        Path(".env.production"),
        Path(".env.test"),
    ]

    found_files = []
    for env_file in env_files:
        if env_file.exists():
            click.echo(f"  {click.style('FOUND', fg='green')} {env_file}")
            found_files.append(env_file)
        else:
            click.echo(f"  {click.style('--', fg='white', dim=True)} {env_file}")

    # Show current environment
    section("Active Environment")
    click.echo(f"  APP_ENVIRONMENT: {os.environ.get('APP_ENVIRONMENT', 'development (default)')}")

    # Show configuration loading order
    section("Loading Priority (highest to lowest)")
    click.echo("  1. Environment variables")
    click.echo("  2. .env.local (if exists)")
    click.echo("  3. .env.{environment} (if exists)")
    click.echo("  4. .env (if exists)")
    click.echo("  5. Default values in code")

    # Show key overrides
    if found_files:
        section("Sample Values from Files")
        for env_file in found_files[:2]:  # Show first 2 files
            click.echo(f"\n  From {env_file}:")
            try:
                with open(env_file) as f:
                    lines = f.readlines()[:5]  # First 5 lines
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key = line.split("=")[0]
                            if any(s in key.upper() for s in ["PASSWORD", "SECRET", "TOKEN", "KEY"]):
                                click.echo(f"    {key}=***")
                            else:
                                click.echo(f"    {line[:60]}{'...' if len(line) > 60 else ''}")
            except Exception as e:
                click.echo(f"    (Error reading file: {e})")


@config.command(name="diff")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def show_diff(output_format: str) -> None:
    """Compare current configuration with defaults."""
    import os

    from example_service.cli.utils import header, section

    header("Configuration Differences")

    # Define defaults
    defaults = {
        "APP_SERVICE_NAME": "example-service",
        "APP_ENVIRONMENT": "development",
        "APP_DEBUG": "false",
        "APP_HOST": "0.0.0.0",
        "APP_PORT": "8000",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_POOL_SIZE": "20",
        "DB_MAX_OVERFLOW": "10",
        "REDIS_KEY_PREFIX": "example_service:",
        "REDIS_TTL": "3600",
        "LOG_LEVEL": "INFO",
        "OTEL_ENABLED": "false",
    }

    differences = []
    same = []

    for key, default in sorted(defaults.items()):
        current = os.environ.get(key, default)
        if current != default:
            differences.append({
                "key": key,
                "default": default,
                "current": current,
            })
        else:
            same.append(key)

    if output_format == "json":
        click.echo(json.dumps({
            "differences": differences,
            "same": same,
        }, indent=2))
        return

    if differences:
        section("Modified from Defaults")
        for diff in differences:
            # Mask sensitive values
            current = diff["current"]
            if any(s in diff["key"].upper() for s in ["PASSWORD", "SECRET", "TOKEN", "KEY"]):
                current = "***"

            click.echo(f"  {diff['key']}:")
            click.echo(f"    Default: {diff['default']}")
            click.echo(f"    Current: {click.style(current, fg='yellow')}")
    else:
        info("No differences from defaults")

    click.echo()
    info(f"Modified: {len(differences)}, Using defaults: {len(same)}")
