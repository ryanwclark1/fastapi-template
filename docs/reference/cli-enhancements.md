# CLI Enhancements - Code Generation & Development Workflows

## Overview

Phase 4 adds powerful code generation and development workflow commands to streamline FastAPI application development. These enhancements reduce boilerplate, enforce best practices, and accelerate feature development.

---

## What Was Added

### 1. Code Generation Commands (770 lines)

**File**: `example_service/cli/commands/generate.py`

Comprehensive scaffolding system that generates production-ready code following FastAPI and SQLAlchemy best practices.

#### Commands

##### `generate resource`

Generate complete CRUD resources with model, schema, CRUD operations, API routes, and tests.

**Usage:**
```bash
# Generate everything
example-service generate resource Product --all

# Generate specific components
example-service generate resource Order --model --schema --crud
example-service generate resource Customer --router --tests

# Overwrite existing files
example-service generate resource Product --all --force
```

**What It Generates:**

1. **SQLAlchemy Model** (`example_service/core/models/{resource}.py`)
   - Base model with `id`, `name`, `description`
   - Automatic timestamps (`created_at`, `updated_at`)
   - Proper type hints with `Mapped`
   - SQLAlchemy 2.0 style

2. **Pydantic Schemas** (`example_service/core/schemas/{resource}.py`)
   - Base schema with common fields
   - Create schema (for POST requests)
   - Update schema (for PUT/PATCH requests)
   - InDB schema (database representation)
   - Public schema (API responses)

3. **CRUD Operations** (`example_service/core/crud/{resource}.py`)
   - `get_{resource}(db, id)` - Fetch by ID with NotFoundException
   - `get_{resources}(db, skip, limit)` - List with pagination
   - `create_{resource}(db, data)` - Create new instance
   - `update_{resource}(db, id, data)` - Update existing
   - `delete_{resource}(db, id)` - Delete instance

4. **API Router** (`example_service/app/routers/{resources}.py`)
   - RESTful endpoints (GET, POST, PUT, DELETE)
   - Authentication with `get_current_user`
   - Rate limiting with `RateLimited`
   - Database dependency injection
   - Proper status codes
   - OpenAPI documentation

5. **Test Suite** (`tests/test_api/test_{resources}.py`)
   - Fixtures for test data
   - Test for each endpoint (list, get, create, update, delete)
   - Test for error cases (404, validation)
   - pytest-asyncio compatible

**Example Generated Code:**

```python
# Model (example_service/core/models/product.py)
class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())

# Schema (example_service/core/schemas/product.py)
class ProductCreate(ProductBase):
    """Schema for creating product."""
    pass

class Product(ProductInDB):
    """Public schema for product."""
    pass

# CRUD (example_service/core/crud/product.py)
async def get_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise NotFoundException(...)
    return product

# Router (example_service/app/routers/products.py)
@router.get("/", response_model=list[Product])
async def list_products(
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    skip: int = 0,
    limit: int = 100,
) -> list[Product]:
    products = await crud.get_products(db, skip=skip, limit=limit)
    return [Product.model_validate(product) for product in products]
```

**Smart Name Conversion:**

The generator automatically handles various naming conventions:

| Input | Class Name | Variable | Plural | Table |
|-------|-----------|----------|---------|-------|
| `Product` | `Product` | `product` | `products` | `products` |
| `UserProfile` | `UserProfile` | `user_profile` | `user_profiles` | `user_profiles` |
| `order_item` | `OrderItem` | `order_item` | `order_items` | `order_items` |

##### `generate router`

Generate a minimal API router with health check endpoint.

**Usage:**
```bash
example-service generate router webhooks --prefix /webhooks
example-service generate router reports --prefix /api --tag "Reports"
```

**Generated File:**
```python
# example_service/app/routers/webhooks.py
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "webhooks"}
```

##### `generate middleware`

Generate a middleware template with logging and error handling.

**Usage:**
```bash
example-service generate middleware audit_log
example-service generate middleware custom_auth
```

**Generated File:**
```python
# example_service/app/middleware/audit_log.py
class AuditLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Pre-processing
        logger.debug(f"Processing request: {request.method} {request.url.path}")

        response = await call_next(request)

        # Post-processing
        logger.debug(f"Request completed: {response.status_code}")

        return response
```

##### `generate migration`

Generate an empty Alembic migration script.

**Usage:**
```bash
example-service generate migration add_user_roles
example-service generate migration create_products_table
```

**Generated File:**
```python
# alembic/versions/20250125_120000_add_user_roles.py
"""
add_user_roles

Revision ID: 20250125
Revises:
Create Date: 2025-01-25T12:00:00
"""

revision = "20250125"
down_revision = None  # Update this to previous revision

def upgrade() -> None:
    """Upgrade database schema."""
    pass

def downgrade() -> None:
    """Downgrade database schema."""
    pass
```

---

### 2. Development Workflow Commands (370 lines)

**File**: `example_service/cli/commands/dev.py`

Streamlined development commands for linting, testing, formatting, and running the server.

#### Commands

##### `dev lint`

Run code linting with ruff.

**Usage:**
```bash
# Check for issues
example-service dev lint

# Auto-fix issues
example-service dev lint --fix

# Watch mode (re-run on changes)
example-service dev lint --watch
```

**Features:**
- Fast linting with ruff
- Auto-fix for common issues
- Watch mode for continuous checking
- Exit code 0 on success, 1 on failure

##### `dev format`

Format code with ruff formatter.

**Usage:**
```bash
# Format code
example-service dev format

# Check formatting without modifying files
example-service dev format --check
```

**Features:**
- Consistent code style
- Black-compatible formatting
- Fast execution

##### `dev typecheck`

Run type checking with mypy.

**Usage:**
```bash
# Basic type checking
example-service dev typecheck

# Strict mode
example-service dev typecheck --strict
```

**Features:**
- Static type analysis
- Catch type-related bugs early
- Optional strict mode

##### `dev test`

Run tests with pytest.

**Usage:**
```bash
# Run all tests
example-service dev test

# With coverage
example-service dev test --coverage

# HTML coverage report
example-service dev test --coverage --html

# Filter by mark
example-service dev test --mark unit
example-service dev test -m integration

# Filter by keyword
example-service dev test --keyword "test_user"
example-service dev test -k "product"

# Verbose output
example-service dev test -v

# Stop on first failure
example-service dev test --failfast
example-service dev test -x

# Test specific path
example-service dev test tests/test_api/
example-service dev test tests/test_api/test_products.py
```

**Features:**
- Full pytest integration
- Coverage analysis
- HTML coverage reports (saved to `htmlcov/`)
- Flexible filtering
- Fast feedback with `--failfast`

##### `dev quality`

Run all quality checks in sequence.

**Usage:**
```bash
# Run all checks
example-service dev quality

# Run all checks with auto-fix
example-service dev quality --fix
```

**Checks Performed:**
1. 🔍 Linting (ruff)
2. 🎨 Formatting (ruff format)
3. 🔬 Type checking (mypy)
4. 🧪 Testing (pytest)

**Output:**
```
🔍 Linting...
============================================================
✅ No linting issues found!

🎨 Formatting...
============================================================
✅ Code is properly formatted!

🔬 Type checking...
============================================================
✅ No type errors found!

🧪 Testing...
============================================================
✅ All tests passed!

============================================================
📊 Quality Check Summary
============================================================
✅ All checks passed!
```

**Use Before:**
- Committing code
- Creating pull requests
- Deploying to production

##### `dev serve`

Run development server with hot-reload.

**Usage:**
```bash
# Default (localhost:8000)
example-service dev serve

# Custom port and host
example-service dev serve --port 8080 --host 0.0.0.0

# Disable reload
example-service dev serve --no-reload

# Multiple workers (production-like)
example-service dev serve --workers 4 --no-reload
```

**Features:**
- Automatic hot-reload on code changes
- Configurable host and port
- Multiple worker support
- Uvicorn-powered

##### `dev clean`

Clean build artifacts and caches.

**Usage:**
```bash
example-service dev clean
```

**Removes:**
- `__pycache__` directories
- `*.pyc`, `*.pyo`, `*.pyd` files
- `.pytest_cache`
- `.mypy_cache`
- `.ruff_cache`
- `htmlcov/` (coverage reports)
- `.coverage` files
- `*.egg-info`
- `dist/` and `build/` directories

##### `dev deps`

Check dependency status and updates.

**Usage:**
```bash
example-service dev deps
```

**Shows:**
- Installed packages with versions
- Outdated packages with available updates
- Dependency tree

##### `dev info`

Show development environment information.

**Usage:**
```bash
# Basic info
example-service dev info

# Full environment info
example-service dev info --all
```

**Displays:**
- Python version
- Project version
- UV version
- Environment variables (with masking for sensitive values)

##### `dev run`

Run arbitrary command in the project environment.

**Usage:**
```bash
# Run Python commands
example-service dev run python --version
example-service dev run python -c "import sys; print(sys.path)"

# Run project scripts
example-service dev run alembic current
example-service dev run pytest -v

# Any command
example-service dev run black --check example_service/
```

**Use Cases:**
- Running tools not exposed as CLI commands
- Quick Python scripts
- Testing individual modules

---

## Integration with Existing CLI

The new commands seamlessly integrate with the existing CLI structure:

```bash
example-service --help
```

**Output:**
```
Example Service CLI - Management commands for FastAPI microservice.

Command Groups:
  db         Database migrations and management
  cache      Redis cache operations
  server     Development and production servers
  config     Configuration management
  tasks      Background task management
  scheduler  Scheduled job management
  users      User account management
  data       Data import/export operations
  monitor    Monitoring and observability
  generate   Code generation and scaffolding          ← NEW
  dev        Development workflow commands            ← NEW

Quick Start:
  example-service db init
  example-service db upgrade
  example-service generate resource Product --all     ← NEW
  example-service dev quality                         ← NEW
```

---

## Complete Workflow Examples

### Example 1: Creating a New Feature

**Goal**: Add a "Product" resource with CRUD operations

```bash
# 1. Generate all components
example-service generate resource Product --all

# 2. Review generated files
# - example_service/core/models/product.py
# - example_service/core/schemas/product.py
# - example_service/core/crud/product.py
# - example_service/app/routers/products.py
# - tests/test_api/test_products.py

# 3. Register model in __init__.py
echo "from example_service.core.models.product import Product" >> example_service/core/models/__init__.py

# 4. Register router in app
# Edit example_service/app/routers/__init__.py to include products router

# 5. Create database migration
example-service db revision -m "add products table"

# 6. Apply migration
example-service db upgrade

# 7. Run quality checks
example-service dev quality

# 8. Run tests
example-service dev test tests/test_api/test_products.py -v

# 9. Start development server
example-service dev serve
```

### Example 2: Development Workflow

**Daily development routine:**

```bash
# Morning: Check environment
example-service dev info --all

# Start development server (separate terminal)
example-service dev serve

# Write code...

# Before each commit:
example-service dev quality --fix

# Run specific tests
example-service dev test -k "product" -v

# Check coverage
example-service dev test --coverage --html
# Open htmlcov/index.html in browser

# Clean up before pushing
example-service dev clean
```

### Example 3: CI/CD Pipeline

**Use in CI/CD:**

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install UV
        run: pip install uv

      - name: Install dependencies
        run: uv sync

      - name: Run quality checks
        run: |
          uv run example-service dev lint
          uv run example-service dev format --check
          uv run example-service dev typecheck
          uv run example-service dev test --coverage
```

### Example 4: Scaffolding Multiple Resources

**Creating a complete feature module:**

```bash
# Generate related resources
example-service generate resource Product --all
example-service generate resource Category --all
example-service generate resource Review --all

# Generate custom router for advanced operations
example-service generate router analytics --prefix /api

# Generate middleware for feature-specific logging
example-service generate middleware product_analytics

# Create migrations
example-service generate migration add_product_tables
# Edit migration to add all tables

# Apply and test
example-service db upgrade
example-service dev test --mark integration
```

---

## Best Practices

### Code Generation

1. **Always review generated code** - Customize fields, add validations, implement business logic
2. **Use meaningful names** - `UserProfile` is better than `Profile`
3. **Register components** - Don't forget to add imports to `__init__.py` files
4. **Create migrations** - Generate and test database migrations after model changes
5. **Write tests** - Customize generated tests to cover edge cases

### Development Workflow

1. **Run quality checks before commits** - Use `dev quality --fix`
2. **Use watch mode during development** - `dev lint --watch` for continuous feedback
3. **Check coverage regularly** - Aim for >80% code coverage
4. **Clean artifacts periodically** - `dev clean` to free up space
5. **Test specific paths** - Faster feedback with targeted tests

### Naming Conventions

**Generated code follows these conventions:**

- **Models**: PascalCase class names (e.g., `Product`, `UserProfile`)
- **Tables**: snake_case plural (e.g., `products`, `user_profiles`)
- **Variables**: snake_case (e.g., `product`, `user_profile`)
- **Endpoints**: kebab-case (e.g., `/products`, `/user-profiles`)
- **Files**: snake_case (e.g., `product.py`, `user_profile.py`)

---

## Configuration

### Environment Variables

The CLI respects these environment variables:

```bash
# Development
export APP_DEBUG=true          # Enable debug mode
export LOG_LEVEL=DEBUG         # Detailed logging

# Testing
export ENVIRONMENT=test        # Use test database
export PYTEST_ARGS="-v --tb=short"  # Default pytest arguments

# Quality checks
export RUFF_ARGS="--fix"       # Auto-fix linting issues
export MYPY_ARGS="--strict"    # Strict type checking
```

### Project Settings

Create `.ruff.toml` for linting configuration:

```toml
[lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "A", "C4", "T20", "SIM"]
ignore = ["E501"]  # Line too long

[format]
line-length = 100
indent-width = 4
```

---

## Tips & Tricks

### Quick Aliases

Add to your shell profile (`.bashrc`, `.zshrc`):

```bash
alias es="example-service"
alias esg="example-service generate"
alias esd="example-service dev"

# Quick commands
alias esq="example-service dev quality --fix"
alias est="example-service dev test"
alias ess="example-service dev serve"
```

Usage:
```bash
esg resource Product --all
esq
est --coverage
ess --port 8080
```

### VSCode Tasks

Add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Quality Check",
      "type": "shell",
      "command": "example-service dev quality --fix",
      "group": "test"
    },
    {
      "label": "Run Tests",
      "type": "shell",
      "command": "example-service dev test --coverage",
      "group": "test"
    },
    {
      "label": "Start Server",
      "type": "shell",
      "command": "example-service dev serve",
      "isBackground": true
    }
  ]
}
```

### Git Hooks

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
echo "Running quality checks..."
example-service dev quality --fix
exit $?
```

Make executable:
```bash
chmod +x .git/hooks/pre-commit
```

---

## Performance

### Code Generation

- **Fast generation**: Generates all files in <100ms
- **No dependencies**: Pure Python, no external templates
- **Smart defaults**: Based on FastAPI/SQLAlchemy best practices

### Development Commands

| Command | Typical Duration | Notes |
|---------|------------------|-------|
| `dev lint` | <1s | Very fast with ruff |
| `dev format` | <1s | Fast formatting |
| `dev typecheck` | 2-5s | Depends on project size |
| `dev test` | 5-30s | Depends on test count |
| `dev quality` | 10-40s | Runs all checks |

---

## Troubleshooting

### Common Issues

**Issue**: Generated code has import errors

**Solution**: Make sure to add imports to `__init__.py` files:
```python
# example_service/core/models/__init__.py
from example_service.core.models.product import Product

# example_service/app/routers/__init__.py
from example_service.app.routers import products
```

**Issue**: Tests fail after generation

**Solution**: Update fixtures to match your authentication setup:
```python
@pytest.fixture
async def auth_headers(test_user) -> dict:
    # Your auth token generation logic
    return {"Authorization": f"Bearer {token}"}
```

**Issue**: `dev quality` fails on CI

**Solution**: Install all dev dependencies:
```bash
uv sync --all-extras
```

**Issue**: Generated model has wrong field types

**Solution**: Edit the generated model and customize field types:
```python
# Change from:
name: Mapped[str] = mapped_column(String(255))

# To:
price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
```

---

## Summary

### Phase 4 Additions

**Code Generation:**
- ✅ 770 lines of scaffolding code
- ✅ 4 generation commands (resource, router, middleware, migration)
- ✅ Smart name conversion and pluralization
- ✅ Production-ready templates

**Development Workflows:**
- ✅ 370 lines of dev tools
- ✅ 10 development commands
- ✅ Integrated quality checks
- ✅ Hot-reload development server

**Total Phase 4:** 1,140 lines of CLI enhancements

---

## Files Created/Modified

**New Files (2):**
- `example_service/cli/commands/generate.py` (770 lines) - Code generation
- `example_service/cli/commands/dev.py` (370 lines) - Development workflows

**Modified Files (2):**
- `example_service/cli/commands/__init__.py` - Export new commands
- `example_service/cli/main.py` - Register new command groups

---

## Next Steps

**Customize Generated Code:**
1. Review and customize generated models
2. Add business logic to CRUD operations
3. Implement custom validators in schemas
4. Add feature-specific tests

**Enhance Workflow:**
1. Set up git hooks with quality checks
2. Configure VSCode tasks
3. Add shell aliases for quick access
4. Integrate into CI/CD pipeline

**Your FastAPI application now has powerful code generation and streamlined development workflows! 🚀**
