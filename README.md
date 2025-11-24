# Example Service

FastAPI microservice template following standard architecture patterns.

## Overview

This service provides a comprehensive template for building FastAPI microservices with:

- Modern Python 3.13+ features
- Structured logging with JSON output
- Health check endpoints
- Database integration with SQLAlchemy
- Async/await throughout
- Comprehensive testing setup
- Docker containerization
- Production-ready configuration

## Features

- **FastAPI** - Modern async web framework
- **SQLAlchemy 2.0+** - Async ORM with type hints
- **Pydantic Settings** - Configuration management
- **Structured Logging** - JSON logs with UTC timestamps
- **Prometheus Metrics** - Observability support
- **Health Checks** - Liveness, readiness, and health endpoints
- **Database Migrations** - Alembic integration
- **Testing** - Pytest with async support
- **Code Quality** - Ruff, MyPy, pre-commit hooks
- **Docker** - Multi-stage builds with uv

## Requirements

- Python 3.13+
- uv (recommended) or pip
- PostgreSQL (optional, for database features)
- Redis (optional, for caching features)

## Quick Start

### Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Copy environment template
cp .env.example .env

# Run the service
uv run uvicorn example_service.app.main:app --reload

# Or use the script entry point
uv run example-service
```

### Using Docker

```bash
# Build and run with docker-compose
cd deployment
docker-compose up --build

# Access the service
curl http://localhost:8000/api/v1/health/
```

## Development

### Setup Development Environment

```bash
# Install all dependencies including dev dependencies
uv sync --all-groups

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=example_service --cov-report=html

# Run linter
uv run ruff check .

# Run formatter
uv run ruff format .

# Run type checker
uv run mypy example_service
```

### Project Structure

```
example_service/
├── app/                    # FastAPI application
│   ├── main.py            # App factory
│   ├── lifespan.py        # Lifecycle management
│   ├── middleware/        # Middleware modules
│   └── router.py          # Router registry
├── core/                   # Core infrastructure
│   ├── settings.py        # Pydantic settings
│   ├── dependencies/      # FastAPI dependencies
│   ├── schemas/           # Shared schemas
│   ├── services/          # Core services
│   └── tasks/             # Background tasks
├── features/              # Feature modules
│   └── status/           # Health check feature
├── infra/                 # Infrastructure
│   ├── database/         # Database session/models
│   ├── logging/          # Logging config
│   ├── metrics/          # Prometheus metrics
│   └── observability/    # Logging/metrics/tracing
└── tests/                # Test suite
    ├── unit/            # Unit tests
    └── integration/     # Integration tests
```

## API Documentation

Once the service is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Health Checks

The service provides three health check endpoints:

- `GET /api/v1/health/` - Overall health status
- `GET /api/v1/health/ready` - Readiness check (dependencies)
- `GET /api/v1/health/live` - Liveness check (basic)

## Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1

# View migration history
uv run alembic history
```

## Configuration

### Modular Settings Architecture

This template uses **Pydantic Settings v2** with a modular, domain-based architecture:

```
example_service/core/settings/
├── __init__.py          # Exports cached loaders
├── loader.py            # LRU-cached settings getters
├── sources.py           # Optional YAML/conf.d support
├── app.py               # Application settings (APP_*)
├── postgres.py          # Database settings (DB_*)
├── redis.py             # Cache settings (REDIS_*)
├── rabbit.py            # Messaging settings (RABBIT_*)
├── auth.py              # Authentication settings (AUTH_*)
├── logging_.py          # Logging settings (LOG_*)
└── otel.py              # OpenTelemetry settings (OTEL_*)
```

### Configuration Precedence

Settings are loaded in this order (highest to lowest priority):

1. **Init kwargs** (testing overrides)
2. **YAML/conf.d files** (optional, local dev)
3. **Environment variables** (production - **recommended**)
4. **.env file** (development only)
5. **secrets_dir** (Kubernetes/Docker secrets)

### Environment Variables

All settings use prefixed environment variables. See `.env.example` for complete documentation.

Key settings examples:

```bash
# Application Settings (APP_*)
APP_SERVICE_NAME=example-service
APP_DEBUG=false
APP_CORS_ORIGINS=["http://localhost:3000"]

# Database Settings (DB_*)
DB_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/example_service

# Redis Cache (REDIS_*)
REDIS_REDIS_URL=redis://localhost:6379/0

# RabbitMQ (RABBIT_*)
RABBIT_RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# Logging (LOG_*)
LOG_LEVEL=INFO
LOG_JSON=true

# OpenTelemetry (OTEL_*)
OTEL_ENABLED=false
OTEL_ENDPOINT=http://localhost:4317
```

### Usage in Code

```python
from example_service.core.settings import get_app_settings, get_db_settings

# Settings are loaded once and cached (LRU)
settings = get_app_settings()
print(settings.service_name)

# Settings are immutable (frozen)
settings.debug = True  # ❌ Raises ValidationError
```

### Optional YAML Configuration

For local development, you can optionally use YAML files (requires `pyyaml`):

```bash
# Install YAML support (optional)
uv sync --group yaml
```

See `conf/` directory for examples. **Note**: Environment variables always override YAML files.

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=example_service --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_core/test_services.py

# Run integration tests only
uv run pytest tests/integration/

# View coverage report
open htmlcov/index.html
```

## Deployment

### Docker

```bash
# Build image
docker build -t example-service:latest .

# Run container
docker run -p 8000:8000 \
  -e EXAMPLE_SERVICE_DATABASE_URL=postgresql+asyncpg://... \
  example-service:latest
```

### Docker Compose

```bash
# Development environment
cd deployment
docker-compose up

# Production environment
cd deployment
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up
```

## Monitoring

The service exposes Prometheus metrics at `/metrics` (if enabled).

Key metrics:
- `http_requests_total` - Total HTTP requests
- `http_request_duration_seconds` - Request duration
- `database_connections_active` - Active DB connections
- `cache_hits_total` / `cache_misses_total` - Cache performance

## Logging

Logs are output in JSON Lines format for easy parsing by log aggregation systems.

Log files are written to `logs/example-service.log.jsonl` with automatic rotation.

## Code Quality

This project uses several tools to maintain code quality:

- **Ruff** - Fast Python linter and formatter
- **MyPy** - Static type checker
- **Pytest** - Testing framework
- **Pre-commit** - Git hooks for quality checks

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linters
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:

- Create an issue in the repository
- Check existing documentation in `docs/`
- Review the architecture guide

## Customization

To adapt this template for your project:

1. **Rename the package**: Replace `example_service` with your service name
2. **Update settings**: Modify `core/settings.py` with your configuration
3. **Update environment prefix**: Change `EXAMPLE_SERVICE_` to your prefix
4. **Add features**: Create new feature modules in `features/`
5. **Configure dependencies**: Update `pyproject.toml` dependencies
6. **Update documentation**: Modify this README and docs as needed

## Next Steps

- [ ] Add your first feature module in `features/`
- [ ] Configure database models in `infra/database/`
- [ ] Set up external service clients in `infra/external/`
- [ ] Add authentication/authorization
- [ ] Configure CI/CD pipelines
- [ ] Set up monitoring and alerting
- [ ] Write comprehensive tests
