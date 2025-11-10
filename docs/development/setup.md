# Development Setup Guide

This guide will help you set up your development environment for working on this service.

## Prerequisites

- Python 3.13+
- Git
- Docker and Docker Compose (optional, for containerized development)
- PostgreSQL (optional, can use Docker)
- Redis (optional, can use Docker)

## Installation

### 1. Install uv

uv is the recommended package manager for this project.

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify installation
uv --version
```

### 2. Clone Repository

```bash
git clone <repository-url>
cd fastapi-template
```

### 3. Install Dependencies

```bash
# Install all dependencies including dev dependencies
uv sync --all-groups

# This creates a virtual environment in .venv/
```

### 4. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your local settings
# At minimum, configure:
# - EXAMPLE_SERVICE_DATABASE_URL (if using database)
# - EXAMPLE_SERVICE_REDIS_URL (if using cache)
```

### 5. Set Up Database (Optional)

If using PostgreSQL:

```bash
# Option 1: Use Docker
docker-compose up -d db

# Option 2: Install locally and create database
createdb example_service

# Run migrations
uv run alembic upgrade head
```

### 6. Install Pre-commit Hooks

```bash
# Install hooks
uv run pre-commit install

# Test hooks
uv run pre-commit run --all-files
```

## Running the Service

### Development Server

```bash
# Run with auto-reload
uv run uvicorn example_service.app.main:app --reload --port 8000

# Or use the configured host/port
uv run uvicorn example_service.app.main:app --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level debug
```

### Using Docker Compose

```bash
# Start all services (app, database, cache)
docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

## Development Workflow

### Making Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes**
   - Add/modify code
   - Update tests
   - Update documentation

3. **Run quality checks**
   ```bash
   # Format code
   uv run ruff format .

   # Lint code
   uv run ruff check . --fix

   # Type check
   uv run mypy example_service

   # Run tests
   uv run pytest
   ```

4. **Commit changes**
   ```bash
   git add .
   git commit -m "feat: add my feature"
   # Pre-commit hooks will run automatically
   ```

5. **Push and create PR**
   ```bash
   git push origin feature/my-feature
   ```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=example_service --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_core/test_services.py

# Run specific test
uv run pytest tests/unit/test_core/test_services.py::test_health_service_check_health

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/

# Run with verbose output
uv run pytest -v

# Run and stop on first failure
uv run pytest -x

# View coverage report
open htmlcov/index.html
```

### Code Quality Tools

#### Ruff (Linting and Formatting)

```bash
# Check for issues
uv run ruff check .

# Fix auto-fixable issues
uv run ruff check . --fix

# Format code
uv run ruff format .

# Check specific file
uv run ruff check example_service/app/main.py
```

#### MyPy (Type Checking)

```bash
# Type check entire project
uv run mypy example_service

# Type check specific file
uv run mypy example_service/app/main.py

# Type check with verbose output
uv run mypy example_service --verbose
```

#### Pre-commit

```bash
# Run all hooks on all files
uv run pre-commit run --all-files

# Run specific hook
uv run pre-commit run ruff --all-files

# Update hooks to latest version
uv run pre-commit autoupdate
```

### Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "add users table"

# Apply migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1

# Rollback all migrations
uv run alembic downgrade base

# View current revision
uv run alembic current

# View migration history
uv run alembic history

# View SQL without applying
uv run alembic upgrade head --sql
```

### Adding New Features

1. **Create feature module**
   ```bash
   mkdir -p example_service/features/my_feature
   touch example_service/features/my_feature/__init__.py
   touch example_service/features/my_feature/router.py
   touch example_service/features/my_feature/schemas.py
   touch example_service/features/my_feature/services.py
   ```

2. **Implement feature files**
   - `router.py` - FastAPI endpoints
   - `schemas.py` - Pydantic models
   - `services.py` - Business logic

3. **Register router**
   ```python
   # In app/router.py
   from example_service.features.my_feature.router import router as my_feature_router

   def setup_routers(app: FastAPI) -> None:
       app.include_router(my_feature_router, prefix="/api/v1")
   ```

4. **Add tests**
   ```bash
   mkdir -p tests/unit/test_features
   touch tests/unit/test_features/test_my_feature.py
   ```

### Environment Variables

Local development uses `.env` file:

```bash
# Development settings
EXAMPLE_SERVICE_DEBUG=true
EXAMPLE_SERVICE_LOG_LEVEL=DEBUG

# Database (local PostgreSQL)
EXAMPLE_SERVICE_DATABASE_URL=postgresql+psycopg://localhost/example_service

# Or use Docker database
EXAMPLE_SERVICE_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/example_service

# Cache (local Redis)
EXAMPLE_SERVICE_REDIS_URL=redis://localhost:6379/0
```

## Troubleshooting

### Common Issues

#### Import Errors

```bash
# Ensure you're in the virtual environment
source .venv/bin/activate  # Unix
.venv\Scripts\activate     # Windows

# Or use uv run
uv run python -c "import example_service"
```

#### Database Connection Errors

```bash
# Check database is running
docker-compose ps db

# Check database URL
echo $EXAMPLE_SERVICE_DATABASE_URL

# Test connection
uv run python -c "from example_service.infra.database.session import engine; import asyncio; asyncio.run(engine.connect())"
```

#### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>

# Or use different port
uv run uvicorn example_service.app.main:app --port 8001
```

### Debugging

#### VS Code

Create `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: FastAPI",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "example_service.app.main:app",
                "--reload",
                "--port",
                "8000"
            ],
            "jinja": true,
            "justMyCode": false
        }
    ]
}
```

#### PyCharm

1. Run → Edit Configurations
2. Add new Python configuration
3. Script path: Path to uvicorn
4. Parameters: `example_service.app.main:app --reload`
5. Working directory: Project root

## API Documentation

Once running, access interactive API docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Next Steps

- Read [Architecture Overview](../architecture/overview.md)
- Check [Testing Guide](testing.md)
- Review [API Documentation](../api/endpoints.md)
- Explore example features in `example_service/features/`
