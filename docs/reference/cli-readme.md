# Example Service CLI

A comprehensive command-line interface for managing the Example Service FastAPI application, built with Click.

## Installation

The CLI is automatically installed when you install the project:

```bash
pip install -e .
```

## Usage

Once installed, you can use the CLI with the `example-service` command:

```bash
example-service --help
```

## Available Commands

### Database Commands (`db`)

Manage database operations and migrations:

```bash
# Initialize and test database connection
example-service db init

# Create a new migration
example-service db migrate -m "Add users table"

# Apply migrations
example-service db upgrade

# Rollback migrations
example-service db downgrade --steps 1

# View migration history
example-service db history

# Show current database revision
example-service db current

# Open interactive database shell (psql)
example-service db shell

# Seed database with sample data
example-service db seed --sample-size 100

# Reset database (drop all tables and re-run migrations)
example-service db reset
```

### Cache Commands (`cache`)

Manage Redis cache:

```bash
# Test Redis connectivity
example-service cache test

# Display Redis server information and statistics
example-service cache info

# Flush all cache keys
example-service cache flush

# Flush keys matching a pattern
example-service cache flush --pattern "user:*"

# List cache keys
example-service cache keys

# List keys with pattern
example-service cache keys --pattern "session:*" --limit 50

# Get value of a specific key
example-service cache get "user:123"
```

### Server Commands (`server`)

Run the application server:

```bash
# Run development server with auto-reload
example-service server dev

# Run on custom host/port
example-service server dev --host 127.0.0.1 --port 8080

# Run without auto-reload
example-service server dev --no-reload --workers 4

# Run production server (no auto-reload, multiple workers)
example-service server prod --workers 4

# Run background task worker
example-service server worker --queue default --concurrency 4

# Run message broker consumer
example-service server broker --queue default
```

### Configuration Commands (`config`)

Manage application configuration:

```bash
# Display current configuration (table format)
example-service config show

# Show configuration in JSON format
example-service config show --format json

# Show configuration with secrets visible
example-service config show --show-secrets

# Validate configuration and check dependencies
example-service config validate

# Generate .env template file
example-service config generate-env

# Generate to custom file
example-service config generate-env -o .env.local

# Get specific configuration value
example-service config get app.service_name
example-service config get database.db_host
```

### Utility Commands

Additional utility commands:

```bash
# Open interactive Python shell with app context
example-service shell

# Run comprehensive health check on all dependencies
example-service health-check

# Export OpenAPI schema
example-service export-openapi

# Export to YAML format
example-service export-openapi --format yaml -o openapi.yaml
```

## Command Groups Overview

### `db` - Database Management
- `init` - Test database connectivity
- `migrate` - Create new migrations
- `upgrade` - Apply migrations
- `downgrade` - Rollback migrations
- `history` - View migration history
- `current` - Show current revision
- `shell` - Interactive database shell
- `seed` - Populate sample data
- `reset` - Reset database

### `cache` - Redis Cache Management
- `test` - Test connectivity
- `info` - Server information
- `flush` - Clear cache keys
- `keys` - List cache keys
- `get` - Get key value

### `server` - Server Operations
- `dev` - Development server
- `prod` - Production server
- `worker` - Background task worker
- `broker` - Message broker consumer

### `config` - Configuration Management
- `show` - Display configuration
- `validate` - Validate settings
- `generate-env` - Create .env template
- `get` - Get specific value

### Standalone Utilities
- `shell` - Interactive Python REPL
- `health-check` - Comprehensive health check
- `export-openapi` - Export API schema

## Examples

### Development Workflow

```bash
# 1. Generate environment file
example-service config generate-env
# Edit .env with your settings

# 2. Validate configuration
example-service config validate

# 3. Initialize database
example-service db init

# 4. Run migrations
example-service db upgrade

# 5. Test cache connection
example-service cache test

# 6. Run health check
example-service health-check

# 7. Start development server
example-service server dev
```

### Working with Database

```bash
# Create a new migration
example-service db migrate -m "Add users table"

# Apply the migration
example-service db upgrade

# Check current state
example-service db current

# Open database shell to verify
example-service db shell
```

### Cache Operations

```bash
# Check cache stats
example-service cache info

# List all keys
example-service cache keys

# Get specific value
example-service cache get "session:abc123"

# Clear specific pattern
example-service cache flush --pattern "temp:*"
```

### Production Deployment

```bash
# Validate everything is configured correctly
example-service config validate

# Run migrations
example-service db upgrade

# Start production server with 4 workers
example-service server prod --workers 4 --no-access-log
```

## Features

- **Async Support**: All commands properly handle async operations
- **Colored Output**: Clear, colored terminal output for better readability
- **Error Handling**: Comprehensive error handling with helpful messages
- **Type Safety**: Full type hints throughout the codebase
- **Modular Design**: Clean separation between command groups
- **Production Ready**: Suitable for development and production use

## Development

To extend the CLI with new commands:

1. Create a new command module in `example_service/cli/commands/`
2. Define your commands using Click decorators
3. Register the command group in `example_service/cli/main.py`

Example:

```python
# example_service/cli/commands/my_feature.py
import click
from example_service.cli.utils import success, error

@click.group(name="my-feature")
def my_feature():
    """My feature commands."""
    pass

@my_feature.command()
def do_something():
    """Do something useful."""
    success("Done!")
```

Then register it in `main.py`:

```python
from example_service.cli.commands import my_feature
cli.add_command(my_feature.my_feature)
```

## Requirements

- Python >= 3.11
- Click >= 8.1.0
- All project dependencies (FastAPI, SQLAlchemy, Redis, etc.)

## License

MIT
