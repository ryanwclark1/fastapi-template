# Testing Guide

This guide explains the testing infrastructure in the FastAPI template and how to easily extend it when adding new features.

## Table of Contents

- [Testing Philosophy](#testing-philosophy)
- [Test Structure](#test-structure)
- [Shared Fixtures](#shared-fixtures)
- [Test Utilities](#test-utilities)
- [Writing New Tests](#writing-new-tests)
- [Best Practices](#best-practices)
- [Examples](#examples)

---

## Testing Philosophy

The template follows these testing principles:

1. **Test Pyramid**: Majority unit tests (fast), fewer integration tests, minimal E2E tests
2. **Isolation**: Tests don't depend on external infrastructure (mocked dependencies)
3. **Maintainability**: Shared fixtures and utilities reduce duplication
4. **Clarity**: Each test has a clear name and docstring
5. **Speed**: All tests run in under 3 seconds for fast feedback

---

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures for all tests
├── utils.py                 # Reusable test utilities and helpers
├── unit/                    # Fast, isolated unit tests
│   ├── test_core/          # Core functionality tests
│   │   ├── test_database/  # Database layer tests
│   │   ├── test_services.py
│   │   └── test_pagination.py
│   ├── test_infra/         # Infrastructure tests
│   │   ├── test_cache/     # Cache utilities tests
│   │   └── test_database_session.py
│   ├── test_middleware/    # Middleware tests
│   └── test_features/      # Feature-specific tests
├── integration/            # Integration tests with real dependencies
│   └── test_database/      # Repository integration tests
└── e2e/                    # End-to-end tests
```

**Organization Principles**:
- `unit/` - Fast tests with mocked dependencies
- `integration/` - Tests with real database/cache (in-memory)
- `e2e/` - Full application tests via HTTP client

---

## Shared Fixtures

All tests have access to fixtures defined in `tests/conftest.py`. These fixtures are organized by category:

### Application Fixtures

```python
async def test_endpoint(app, client):
    """Test using FastAPI app and HTTP client."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
```

**Available Fixtures**:
- `app` - FastAPI application instance
- `client` - Async HTTP client for making requests

### Database Fixtures

```python
async def test_create_user(db_session, current_user):
    """Test using database session and audit user."""
    user = User(email="test@example.com")
    user.created_by = current_user["email"]

    db_session.add(user)
    await db_session.commit()

    assert user.id is not None
```

**Available Fixtures**:
- `db_engine` - Async SQLAlchemy engine (in-memory SQLite)
- `db_session` - Async database session with automatic cleanup
- `current_user` - Simulated current user for audit tracking
- `admin_user` - Simulated admin user for audit tracking

### Cache Fixtures

```python
async def test_cache_operations(mock_redis_client, mock_cache):
    """Test using mocked Redis client."""
    await mock_redis_client.set("key", "value")
    value = await mock_redis_client.get("key")
    assert value == "value"
```

**Available Fixtures**:
- `mock_redis_client` - Comprehensive Redis mock
- `mock_cache` - Mock cache for decorator testing

### Authentication Fixtures

```python
async def test_protected_endpoint(client, mock_auth_token):
    """Test using authentication token."""
    headers = {"Authorization": f"Bearer {mock_auth_token}"}
    response = await client.get("/api/v1/protected", headers=headers)
    assert response.status_code == 200
```

**Available Fixtures**:
- `mock_auth_token` - JWT-like token string
- `mock_auth_user` - Authenticated user with permissions

### Utility Fixtures

```python
def test_with_current_time(utc_now, sample_ids):
    """Test using utility fixtures."""
    user_id = sample_ids["user_id"]
    timestamp = utc_now
    assert isinstance(user_id, int)
    assert timestamp.tzinfo is not None
```

**Available Fixtures**:
- `utc_now` - Current UTC datetime
- `sample_ids` - Dictionary with various ID formats
- `anyio_backend` - Configured for async tests

### Factory Fixtures

```python
def test_with_factories(make_test_model, make_test_users):
    """Test using factory fixtures."""
    # Create single model
    user = make_test_model(User, email="test@example.com")

    # Create multiple users
    users = make_test_users(count=5)
    assert len(users) == 5
```

**Available Fixtures**:
- `make_test_model` - Generic model factory
- `make_test_users` - User factory with audit tracking

### Parametrize Helpers

```python
def test_all_pk_strategies(primary_key_strategy):
    """Test runs 3 times for each PK strategy."""
    assert primary_key_strategy in ["integer", "uuid_v4", "uuid_v7"]

def test_deletion_modes(with_soft_delete):
    """Test runs twice for soft/hard delete."""
    if with_soft_delete:
        # Test soft delete behavior
        pass
    else:
        # Test hard delete behavior
        pass
```

**Available Fixtures**:
- `primary_key_strategy` - Parametrized PK strategies
- `with_soft_delete` - Parametrized soft/hard delete

---

## Test Utilities

The `tests/utils.py` module provides reusable utilities:

### Model Factories

Create test data with realistic defaults:

```python
from tests.utils import ModelFactory

# Create user data
user_data = ModelFactory.create_user(
    email="test@example.com",
    created_by="admin@example.com"
)
user = User(**user_data)

# Create batch of users
users_data = ModelFactory.create_batch(
    ModelFactory.create_user,
    count=5,
    created_by="admin@example.com"
)
```

### Assertion Helpers

Reusable assertions for common scenarios:

```python
from tests.utils import (
    assert_audit_trail,
    assert_soft_deleted,
    assert_timestamps_updated,
    assert_primary_key_set,
)

# Assert audit trail is correct
assert_audit_trail(
    user,
    created_by="admin@example.com",
    updated_by="user@example.com"
)

# Assert soft delete fields are set
assert_soft_deleted(user, deleted_by="admin@example.com")

# Assert timestamp updated
original = user.updated_at
user.name = "New Name"
await session.commit()
assert_timestamps_updated(user, original)

# Assert primary key is set
assert_primary_key_set(user, expected_type=int)
```

### Database Helpers

Simplify database test operations:

```python
from tests.utils import create_and_commit, create_batch_and_commit

# Create single model
user = User(email="test@example.com")
user = await create_and_commit(session, user)

# Create multiple models
users = [User(email=f"user{i}@example.com") for i in range(5)]
users = await create_batch_and_commit(session, users)
```

### Cache Test Helper

Helper class for cache testing:

```python
from tests.utils import CacheTestHelper

helper = CacheTestHelper(mock_redis_client)
await helper.set("key", "value", ttl=300)
assert await helper.exists("key")
value = await helper.get("key")
await helper.delete("key")
await helper.clear()
```

### Fluent Builders

Build complex test data using fluent interface:

```python
from tests.utils import UserBuilder, DocumentBuilder

# Build user with fluent interface
user_data = (
    UserBuilder()
    .with_email("test@example.com")
    .with_name("Test User")
    .with_audit("admin@example.com")
    .build()
)

# Build document
doc_data = (
    DocumentBuilder()
    .with_title("My Document")
    .with_content("Important content")
    .with_audit("user@example.com")
    .build()
)
```

---

## Writing New Tests

### 1. Choose the Right Test Type

**Unit Test** - Fast, isolated, mocked dependencies:
```python
# tests/unit/test_features/test_my_feature.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_my_function(mock_cache):
    """Test my function with mocked cache."""
    result = await my_function()
    assert result == expected_value
```

**Integration Test** - Real dependencies (in-memory):
```python
# tests/integration/test_my_feature_integration.py
import pytest

@pytest.mark.asyncio
async def test_feature_with_database(db_session, current_user):
    """Test feature with real database."""
    # Use real database operations
    model = MyModel(name="test")
    model.created_by = current_user["email"]

    db_session.add(model)
    await db_session.commit()

    assert model.id is not None
```

### 2. Use Existing Fixtures

Leverage shared fixtures from `conftest.py`:

```python
async def test_with_fixtures(
    db_session,      # Database session
    current_user,    # Audit tracking
    mock_cache,      # Cache mock
    utc_now,         # Current time
):
    """Test using multiple fixtures."""
    # Fixtures are automatically injected
    pass
```

### 3. Use Test Utilities

Import utilities from `tests/utils.py`:

```python
from tests.utils import (
    ModelFactory,
    assert_audit_trail,
    create_and_commit,
    UserBuilder,
)

async def test_with_utilities(db_session, current_user):
    """Test using utilities for cleaner code."""
    # Create user with factory
    user_data = ModelFactory.create_user(
        email="test@example.com",
        created_by=current_user["email"]
    )
    user = User(**user_data)

    # Create and commit helper
    user = await create_and_commit(db_session, user)

    # Assert helper
    assert_audit_trail(user, created_by=current_user["email"])
```

### 4. Follow Naming Conventions

```python
# Good test names - descriptive and specific
async def test_create_user_sets_audit_fields()
async def test_soft_delete_excludes_from_queries()
async def test_cache_invalidation_clears_related_entries()

# Bad test names - vague
async def test_user()
async def test_delete()
async def test_cache()
```

### 5. Write Clear Docstrings

```python
async def test_soft_delete_recovery():
    """Test that soft-deleted records can be recovered.

    This test verifies that setting deleted_at and deleted_by to None
    effectively recovers a soft-deleted record, making it queryable again.
    """
    # Test implementation...
```

---

## Best Practices

### 1. Arrange-Act-Assert Pattern

```python
async def test_update_user_sets_updated_by(db_session, current_user, admin_user):
    """Test that updates set updated_by field."""
    # Arrange - Set up test data
    user = User(email="test@example.com")
    user.created_by = current_user["email"]
    await create_and_commit(db_session, user)

    # Act - Perform the operation
    user.name = "Updated Name"
    user.updated_by = admin_user["email"]
    await db_session.commit()
    await db_session.refresh(user)

    # Assert - Verify the results
    assert user.updated_by == admin_user["email"]
    assert user.created_by == current_user["email"]  # Should not change
```

### 2. Test One Thing Per Test

```python
# Good - Tests one specific behavior
async def test_soft_delete_sets_deleted_at():
    """Test that soft delete sets deleted_at timestamp."""
    pass

async def test_soft_delete_sets_deleted_by():
    """Test that soft delete sets deleted_by field."""
    pass

# Bad - Tests multiple behaviors
async def test_soft_delete():
    """Test soft delete functionality."""
    # Tests deleted_at, deleted_by, is_deleted, querying, recovery, etc.
    pass
```

### 3. Use Fixtures for Setup, Not in Tests

```python
# Good - Setup in fixtures
@pytest.fixture
async def user_with_posts(db_session):
    user = User(email="test@example.com")
    user.posts = [Post(title=f"Post {i}") for i in range(3)]
    return await create_and_commit(db_session, user)

async def test_user_has_posts(user_with_posts):
    assert len(user_with_posts.posts) == 3

# Bad - Setup in test
async def test_user_has_posts(db_session):
    user = User(email="test@example.com")
    user.posts = [Post(title=f"Post {i}") for i in range(3)]
    await create_and_commit(db_session, user)
    assert len(user.posts) == 3
```

### 4. Test Edge Cases

```python
async def test_audit_fields_handle_anonymous_operations():
    """Test that audit fields work when user is unknown."""
    user = User(email="test@example.com")
    # No created_by set (anonymous operation)
    assert user.created_by is None  # Should not fail

async def test_soft_delete_handles_multiple_cycles():
    """Test repeated delete and recover cycles."""
    for i in range(3):
        user.deleted_at = datetime.now(UTC)
        user.deleted_by = "admin@example.com"
        # Recover
        user.deleted_at = None
        user.deleted_by = None
    # Should handle gracefully
```

### 5. Use Parametrize for Multiple Cases

```python
@pytest.mark.parametrize("email,valid", [
    ("valid@example.com", True),
    ("invalid.email", False),
    ("", False),
    (None, False),
])
async def test_email_validation(email, valid):
    """Test email validation with various inputs."""
    if valid:
        user = User(email=email)
        assert user.email == email
    else:
        with pytest.raises(ValueError):
            User(email=email)
```

---

## Examples

### Example 1: Adding Tests for a New Model

Let's say you add a new `Product` model with audit trail and soft delete:

```python
# example_service/features/products/models.py
from example_service.core.database.base import (
    Base, IntegerPKMixin, TimestampMixin,
    AuditColumnsMixin, SoftDeleteMixin
)

class Product(
    Base,
    IntegerPKMixin,
    TimestampMixin,
    AuditColumnsMixin,
    SoftDeleteMixin
):
    __tablename__ = "products"
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
```

**Step 1**: Add factory to `tests/utils.py`:

```python
# tests/utils.py
class ModelFactory:
    @staticmethod
    def create_product(
        name: str | None = None,
        price: Decimal | None = None,
        created_by: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create product model data with defaults."""
        data = {
            "name": name or "Test Product",
            "price": price or Decimal("99.99"),
        }
        if created_by:
            data["created_by"] = created_by
        data.update(kwargs)
        return data
```

**Step 2**: Create test file:

```python
# tests/unit/test_features/test_products/test_models.py
import pytest
from decimal import Decimal
from datetime import UTC, datetime

from example_service.features.products.models import Product
from tests.utils import (
    ModelFactory,
    assert_audit_trail,
    assert_soft_deleted,
    create_and_commit,
)

@pytest.mark.asyncio
async def test_create_product_sets_audit_fields(db_session, current_user):
    """Test that creating a product sets audit fields."""
    # Arrange
    product_data = ModelFactory.create_product(
        name="Test Product",
        price=Decimal("49.99"),
        created_by=current_user["email"]
    )
    product = Product(**product_data)

    # Act
    product = await create_and_commit(db_session, product)

    # Assert
    assert_audit_trail(product, created_by=current_user["email"])
    assert product.name == "Test Product"
    assert product.price == Decimal("49.99")

@pytest.mark.asyncio
async def test_soft_delete_product(db_session, current_user, admin_user):
    """Test soft deleting a product."""
    # Arrange
    product_data = ModelFactory.create_product(created_by=current_user["email"])
    product = Product(**product_data)
    product = await create_and_commit(db_session, product)

    # Act - Soft delete
    product.deleted_at = datetime.now(UTC)
    product.deleted_by = admin_user["email"]
    await db_session.commit()
    await db_session.refresh(product)

    # Assert
    assert_soft_deleted(product, deleted_by=admin_user["email"])
```

### Example 2: Adding Tests for a New Service

```python
# example_service/features/products/service.py
from example_service.infra.cache import cached, invalidate_tags

class ProductService:
    @cached(
        key_prefix="product",
        ttl=300,
        tags=lambda product_id: [f"product:{product_id}", "products:all"]
    )
    async def get_product(self, product_id: int) -> Product:
        """Get product with caching."""
        return await self.repository.get(session, product_id)

    async def update_product(self, product_id: int, data: dict) -> Product:
        """Update product and invalidate cache."""
        product = await self.repository.update(session, product_id, **data)
        await invalidate_tags([f"product:{product_id}", "products:all"])
        return product
```

**Test file**:

```python
# tests/unit/test_features/test_products/test_service.py
import pytest
from unittest.mock import AsyncMock, patch

from example_service.features.products.service import ProductService
from tests.utils import ModelFactory

@pytest.mark.asyncio
@patch("example_service.features.products.service.invalidate_tags")
async def test_update_product_invalidates_cache(
    mock_invalidate,
    mock_cache,
):
    """Test that updating a product invalidates related cache entries."""
    # Arrange
    service = ProductService()
    product_id = 1
    update_data = {"name": "Updated Product"}

    # Mock repository
    service.repository = AsyncMock()
    service.repository.update.return_value = Product(id=product_id, name="Updated Product")

    # Act
    await service.update_product(product_id, update_data)

    # Assert
    mock_invalidate.assert_called_once_with([
        f"product:{product_id}",
        "products:all"
    ])
```

### Example 3: Integration Test for New Feature

```python
# tests/integration/test_features/test_products_integration.py
import pytest
from decimal import Decimal

from example_service.features.products.models import Product
from example_service.features.products.repository import ProductRepository
from tests.utils import ModelFactory, assert_audit_trail, create_and_commit

@pytest.mark.asyncio
async def test_product_complete_lifecycle(db_session, current_user, admin_user):
    """Test complete product lifecycle: create → update → soft delete → recover."""
    repo = ProductRepository()

    # Create
    product_data = ModelFactory.create_product(
        name="Lifecycle Product",
        price=Decimal("29.99"),
        created_by=current_user["email"]
    )
    product = Product(**product_data)
    product = await repo.create(db_session, product)

    assert_audit_trail(product, created_by=current_user["email"])
    assert product.name == "Lifecycle Product"

    # Update
    product.name = "Updated Product"
    product.price = Decimal("39.99")
    product.updated_by = admin_user["email"]
    await db_session.commit()
    await db_session.refresh(product)

    assert product.name == "Updated Product"
    assert product.updated_by == admin_user["email"]

    # Soft Delete
    product.deleted_at = datetime.now(UTC)
    product.deleted_by = admin_user["email"]
    await db_session.commit()

    assert product.is_deleted
    assert product.deleted_by == admin_user["email"]

    # Recover
    product.deleted_at = None
    product.deleted_by = None
    await db_session.commit()

    assert not product.is_deleted
```

---

## Summary

The testing infrastructure is designed to be:

1. **Easy to Extend**: Add fixtures to `conftest.py`, utilities to `utils.py`
2. **Reusable**: Shared fixtures and utilities reduce duplication
3. **Fast**: In-memory databases and mocked dependencies
4. **Clear**: Descriptive names, docstrings, and organization
5. **Maintainable**: Follow consistent patterns and best practices

When adding new features:
1. Use existing fixtures from `conftest.py`
2. Add new fixtures/utilities as needed
3. Follow naming conventions and patterns
4. Write unit tests first, then integration tests
5. Use assertion helpers and factories from `utils.py`

**Happy Testing!** 🧪
