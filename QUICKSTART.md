# Quick Start Guide

Get started with the FastAPI service template in minutes!

## Prerequisites

- Python 3.13
- uv (for dependency management)
- Docker (optional, for PostgreSQL/Redis/RabbitMQ)

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd fastapi-template

# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
```

## CLI Commands

The service includes a comprehensive Click CLI:

```bash
# Show all available commands
example-service --help

# Show version
example-service --version
```

### Running the Server

```bash
# Development server with auto-reload
example-service run dev

# Production server
example-service run server --workers 4

# Custom host and port
example-service run server --host 0.0.0.0 --port 8080

# With reload for development
example-service run server --reload
```

### Database Management

```bash
# Create database tables
example-service db init

# Check database connection
example-service db check

# Reset database (⚠️ deletes all data)
example-service db reset --yes

# Open database shell
example-service db shell
```

### Utility Commands

```bash
# Show service information
example-service utils info

# Show configuration
example-service utils config

# Check health (requires running server)
example-service utils health --url http://localhost:8000

# List all routes
example-service utils routes
```

### Worker Commands

```bash
# Run background task worker
example-service run worker

# Custom queue and concurrency
example-service run worker --queues default,priority --concurrency 8
```

## Quick Start

1. **Initialize the database:**
   ```bash
   example-service db init
   ```

2. **Start the development server:**
   ```bash
   example-service run dev
   ```

3. **Access the API:**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc
   - Health Check: http://localhost:8000/api/v1/health/

## Items API Examples

### Create an Item

```bash
curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Buy groceries",
    "description": "Milk, eggs, bread",
    "is_completed": false
  }'
```

### List Items

```bash
# Get all items
curl http://localhost:8000/api/v1/items/

# With pagination
curl "http://localhost:8000/api/v1/items/?page=1&page_size=20"

# Filter by completion status
curl "http://localhost:8000/api/v1/items/?completed=false"
```

### Get Specific Item

```bash
curl http://localhost:8000/api/v1/items/{item-id}
```

### Update Item

```bash
curl -X PATCH http://localhost:8000/api/v1/items/{item-id} \
  -H "Content-Type: application/json" \
  -d '{
    "is_completed": true,
    "description": "Updated description"
  }'
```

### Delete Item

```bash
curl -X DELETE http://localhost:8000/api/v1/items/{item-id}
```

## Demo Script

Run the interactive demo to see all endpoints in action:

```bash
# Start the server in one terminal
example-service run dev

# Run the demo in another terminal
./demo_api.sh
```

## Environment Configuration

Create a `.env` file for configuration:

```env
# Application
APP_SERVICE_NAME=example-service
APP_ENVIRONMENT=development
APP_DEBUG=true

# Database (optional - uses SQLite by default)
DB_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/db

# Redis (optional)
REDIS_REDIS_URL=redis://localhost:6379/0

# RabbitMQ (optional)
RABBIT_RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# Logging
LOG_LEVEL=INFO
LOG_JSON_FORMAT=true

# OpenTelemetry (optional)
OTEL_ENABLED=false
OTEL_ENDPOINT=http://tempo:4317
```

## Architecture Overview

```
example_service/
├── app/                  # FastAPI application
│   ├── main.py          # App factory
│   ├── lifespan.py      # Startup/shutdown
│   ├── middleware.py    # CORS, logging, etc.
│   └── router.py        # Route registry
├── cli/                  # Click CLI commands
│   ├── main.py          # CLI entry point
│   └── commands/        # Command groups
├── core/                 # Core business logic
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # Business logic
│   ├── dependencies/    # FastAPI dependencies
│   └── settings/        # Configuration
├── features/             # Feature modules
│   ├── items/           # Items CRUD feature
│   └── status/          # Health checks
└── infra/                # Infrastructure
    ├── database/        # Database config
    ├── cache/           # Redis cache
    ├── messaging/       # RabbitMQ
    ├── tasks/           # Background tasks
    └── tracing/         # OpenTelemetry
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=example_service --cov-report=html

# Run specific test file
pytest tests/unit/test_core/test_settings.py

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration
```

## Next Steps

1. **Customize the Item Model**: Edit `example_service/core/models/item.py`
2. **Add New Features**: Create new modules in `example_service/features/`
3. **Configure Services**: Add PostgreSQL, Redis, RabbitMQ via environment variables
4. **Add Authentication**: Implement real auth in `example_service/core/dependencies/auth.py`
5. **Add Background Tasks**: Create tasks in `example_service/infra/tasks/tasks.py`
6. **Enable Tracing**: Configure OpenTelemetry for distributed tracing

## Troubleshooting

### Database Connection Errors

```bash
# Check database connection
example-service db check

# Verify configuration
example-service utils config | grep DATABASE
```

### Import Errors

```bash
# Reinstall dependencies
uv sync

# Ensure virtual environment is activated
source .venv/bin/activate
```

### Port Already in Use

```bash
# Use a different port
example-service run server --port 8080
```

## Getting Help

```bash
# CLI help
example-service --help
example-service run --help
example-service db --help

# API Documentation
# Visit http://localhost:8000/docs after starting the server
```
