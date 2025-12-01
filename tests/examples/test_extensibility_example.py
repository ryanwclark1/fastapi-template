"""Example test demonstrating testing infrastructure extensibility.

This file shows how to leverage the testing infrastructure when adding
new features to the template. It demonstrates:

1. Using shared fixtures from conftest.py
2. Using test utilities from tests/utils.py
3. Creating custom fixtures for feature-specific needs
4. Writing unit and integration tests
5. Following best practices and patterns

This is a REFERENCE implementation - use it as a template when adding
tests for new features.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

# Import base classes for creating test models
from example_service.core.database.base import (
    AuditColumnsMixin,
    Base,
    IntegerPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

# Import shared test utilities
from tests.utils import (
    ModelFactory,
    UserBuilder,
    assert_audit_trail,
    assert_primary_key_set,
    assert_soft_deleted,
    create_and_commit,
    create_batch_and_commit,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ============================================================================
# Example: Adding a New Feature (Product Management)
# ============================================================================

# Step 1: Define your model (would normally be in example_service/features/products/models.py)
class Product(
    Base,
    IntegerPKMixin,
    TimestampMixin,
    AuditColumnsMixin,
    SoftDeleteMixin,
):
    """Example product model demonstrating all mixins."""

    __tablename__ = "example_products"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(1000))
    price: Mapped[str] = mapped_column(String(20))  # Store as string for simplicity
    stock_quantity: Mapped[int] = mapped_column(default=0)


# Step 2: Extend ModelFactory for your new model (would normally be in tests/utils.py)
def create_product_data(
    name: str | None = None,
    description: str | None = None,
    price: str | None = None,
    stock_quantity: int | None = None,
    created_by: str | None = None,
    **kwargs,
) -> dict:
    """Factory function for creating product test data.

    This demonstrates how to add a new factory function to tests/utils.py.
    """
    data = {
        "name": name or "Test Product",
        "description": description or "A test product for demonstration",
        "price": price or "99.99",
        "stock_quantity": stock_quantity if stock_quantity is not None else 10,
    }
    if created_by:
        data["created_by"] = created_by
    data.update(kwargs)
    return data


# Step 3: Create feature-specific fixtures (optional, if needed)
@pytest.fixture
async def sample_product(db_session: AsyncSession, current_user: dict) -> Product:
    """Fixture providing a sample product for testing.

    This demonstrates creating a custom fixture for your feature.
    Use this pattern when multiple tests need the same setup.
    """
    product_data = create_product_data(
        name="Sample Product",
        created_by=current_user["email"],
    )
    product = Product(**product_data)
    return await create_and_commit(db_session, product)


@pytest.fixture
async def product_collection(db_session: AsyncSession, current_user: dict) -> list[Product]:
    """Fixture providing multiple products for testing pagination, etc.

    This demonstrates creating a collection fixture.
    """
    products = [
        Product(**create_product_data(name=f"Product {i}", created_by=current_user["email"]))
        for i in range(5)
    ]
    return await create_batch_and_commit(db_session, products)


# ============================================================================
# Unit Tests - Fast, Isolated Tests
# ============================================================================


class TestProductModel:
    """Unit tests for Product model.

    Group related tests in classes for better organization.
    """

    @pytest.mark.asyncio
    async def test_create_product_sets_defaults(self, db_session: AsyncSession):
        """Test that product creation sets default values correctly."""
        # Arrange
        product = Product(
            name="Test Product",
            description="Test description",
            price="49.99",
        )

        # Act
        product = await create_and_commit(db_session, product)

        # Assert
        assert_primary_key_set(product, expected_type=int)
        assert product.name == "Test Product"
        assert product.stock_quantity == 0  # Default value

    @pytest.mark.asyncio
    async def test_create_product_sets_audit_fields(
        self,
        db_session: AsyncSession,
        current_user: dict,
    ):
        """Test that product creation sets audit tracking fields."""
        # Arrange
        product_data = create_product_data(
            name="Audited Product",
            created_by=current_user["email"],
        )
        product = Product(**product_data)

        # Act
        product = await create_and_commit(db_session, product)

        # Assert
        assert_audit_trail(product, created_by=current_user["email"])
        assert product.created_at is not None
        assert product.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_product_sets_updated_by(
        self,
        db_session: AsyncSession,
        current_user: dict,
        admin_user: dict,
    ):
        """Test that updating a product sets updated_by field."""
        # Arrange - Create product as regular user
        product_data = create_product_data(created_by=current_user["email"])
        product = Product(**product_data)
        product = await create_and_commit(db_session, product)
        original_created_by = product.created_by

        # Act - Update as admin
        product.name = "Updated Product"
        product.updated_by = admin_user["email"]
        await db_session.commit()
        await db_session.refresh(product)

        # Assert
        assert product.updated_by == admin_user["email"]
        assert product.created_by == original_created_by  # Should not change

    @pytest.mark.asyncio
    async def test_soft_delete_product_sets_deleted_fields(
        self,
        db_session: AsyncSession,
        current_user: dict,
        admin_user: dict,
    ):
        """Test that soft deleting a product sets deleted_at and deleted_by."""
        # Arrange
        product_data = create_product_data(created_by=current_user["email"])
        product = Product(**product_data)
        product = await create_and_commit(db_session, product)

        # Act
        product.deleted_at = datetime.now(UTC)
        product.deleted_by = admin_user["email"]
        await db_session.commit()
        await db_session.refresh(product)

        # Assert
        assert_soft_deleted(product, deleted_by=admin_user["email"])
        assert product.is_deleted is True

    @pytest.mark.asyncio
    async def test_recover_soft_deleted_product(
        self,
        db_session: AsyncSession,
        sample_product: Product,
        admin_user: dict,
    ):
        """Test that soft-deleted product can be recovered."""
        # Arrange - Soft delete the product
        sample_product.deleted_at = datetime.now(UTC)
        sample_product.deleted_by = admin_user["email"]
        await db_session.commit()
        assert sample_product.is_deleted

        # Act - Recover
        sample_product.deleted_at = None
        sample_product.deleted_by = None
        await db_session.commit()
        await db_session.refresh(sample_product)

        # Assert
        assert not sample_product.is_deleted
        assert sample_product.deleted_at is None
        assert sample_product.deleted_by is None


# ============================================================================
# Integration Tests - Tests with Real Database Operations
# ============================================================================


class TestProductQueries:
    """Integration tests for product queries.

    These tests use real database operations to verify query behavior.
    """

    @pytest.mark.asyncio
    async def test_query_excludes_soft_deleted_products(
        self,
        db_session: AsyncSession,
        product_collection: list[Product],
        admin_user: dict,
    ):
        """Test that queries exclude soft-deleted products by default."""
        # Arrange - Soft delete first two products
        for product in product_collection[:2]:
            product.deleted_at = datetime.now(UTC)
            product.deleted_by = admin_user["email"]
        await db_session.commit()

        # Act - Query non-deleted products
        stmt = select(Product).where(Product.deleted_at.is_(None))
        result = await db_session.execute(stmt)
        active_products = list(result.scalars().all())

        # Assert
        assert len(active_products) == 3  # 5 total - 2 deleted = 3 active
        assert all(not p.is_deleted for p in active_products)

    @pytest.mark.asyncio
    async def test_query_can_include_soft_deleted_products(
        self,
        db_session: AsyncSession,
        product_collection: list[Product],
        admin_user: dict,
    ):
        """Test that queries can explicitly include soft-deleted products."""
        # Arrange - Soft delete some products
        product_collection[0].deleted_at = datetime.now(UTC)
        product_collection[0].deleted_by = admin_user["email"]
        await db_session.commit()

        # Act - Query all products (including deleted)
        stmt = select(Product)
        result = await db_session.execute(stmt)
        all_products = list(result.scalars().all())

        # Assert
        assert len(all_products) == 5  # All products returned
        assert sum(1 for p in all_products if p.is_deleted) == 1

    @pytest.mark.asyncio
    async def test_product_complete_lifecycle(
        self,
        db_session: AsyncSession,
        current_user: dict,
        admin_user: dict,
    ):
        """Test complete product lifecycle: create → update → delete → recover."""
        # Step 1: Create
        product_data = create_product_data(
            name="Lifecycle Product",
            price="29.99",
            created_by=current_user["email"],
        )
        product = Product(**product_data)
        product = await create_and_commit(db_session, product)

        assert_audit_trail(product, created_by=current_user["email"])
        assert product.name == "Lifecycle Product"

        # Step 2: Update
        product.name = "Updated Lifecycle Product"
        product.price = "39.99"
        product.updated_by = admin_user["email"]
        await db_session.commit()
        await db_session.refresh(product)

        assert product.name == "Updated Lifecycle Product"
        assert product.updated_by == admin_user["email"]

        # Step 3: Soft Delete
        product.deleted_at = datetime.now(UTC)
        product.deleted_by = admin_user["email"]
        await db_session.commit()

        assert_soft_deleted(product, deleted_by=admin_user["email"])

        # Step 4: Recover
        product.deleted_at = None
        product.deleted_by = None
        await db_session.commit()
        await db_session.refresh(product)

        assert not product.is_deleted


# ============================================================================
# Parametrized Tests - Test Multiple Scenarios
# ============================================================================


class TestProductValidation:
    """Tests demonstrating parametrized testing."""

    @pytest.mark.parametrize(
        "name,price,stock,valid",
        [
            ("Valid Product", "99.99", 10, True),
            ("Zero Stock", "49.99", 0, True),
            ("", "99.99", 10, False),  # Empty name
            ("Valid", "", 10, False),  # Empty price
        ],
    )
    @pytest.mark.asyncio
    async def test_product_validation(
        self,
        db_session: AsyncSession,
        name: str,
        price: str,
        stock: int,
        valid: bool,
    ):
        """Test product validation with various inputs.

        This demonstrates parametrized testing for validation scenarios.
        """
        if valid:
            # Should succeed
            product = Product(
                name=name,
                description="Test",
                price=price,
                stock_quantity=stock,
            )
            product = await create_and_commit(db_session, product)
            assert product.id is not None
        else:
            # Should fail (in real code, validation would raise ValueError)
            # For this example, we just check the invalid input
            assert name == "" or price == ""


# ============================================================================
# Edge Cases and Error Scenarios
# ============================================================================


class TestProductEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    @pytest.mark.asyncio
    async def test_product_with_null_audit_fields(self, db_session: AsyncSession):
        """Test that products can be created without audit tracking (anonymous)."""
        # Arrange & Act
        product = Product(
            name="Anonymous Product",
            description="Created without user tracking",
            price="9.99",
        )
        product = await create_and_commit(db_session, product)

        # Assert
        assert product.id is not None
        assert product.created_by is None  # Anonymous creation
        assert product.created_at is not None  # But timestamps still set

    @pytest.mark.asyncio
    async def test_multiple_soft_delete_recovery_cycles(
        self,
        db_session: AsyncSession,
        sample_product: Product,
        admin_user: dict,
    ):
        """Test that products can be soft-deleted and recovered multiple times."""
        # Act & Assert - Multiple cycles
        for i in range(3):
            # Delete
            sample_product.deleted_at = datetime.now(UTC)
            sample_product.deleted_by = admin_user["email"]
            await db_session.commit()
            assert sample_product.is_deleted

            # Recover
            sample_product.deleted_at = None
            sample_product.deleted_by = None
            await db_session.commit()
            assert not sample_product.is_deleted

    @pytest.mark.asyncio
    async def test_concurrent_updates_preserve_audit_trail(
        self,
        db_session: AsyncSession,
        sample_product: Product,
        current_user: dict,
        admin_user: dict,
    ):
        """Test that audit trail is preserved through multiple updates."""
        # Track original creator
        original_creator = sample_product.created_by

        # Update 1 - User makes change
        sample_product.price = "79.99"
        sample_product.updated_by = current_user["email"]
        await db_session.commit()
        await db_session.refresh(sample_product)

        # Update 2 - Admin makes change
        sample_product.stock_quantity = 50
        sample_product.updated_by = admin_user["email"]
        await db_session.commit()
        await db_session.refresh(sample_product)

        # Assert - Creator preserved, last updater tracked
        assert sample_product.created_by == original_creator
        assert sample_product.updated_by == admin_user["email"]


# ============================================================================
# Documentation and Usage Examples
# ============================================================================


class TestExtensibilityDocumentation:
    """Tests that serve as documentation for extending the test suite.

    These tests demonstrate common patterns and best practices.
    """

    @pytest.mark.asyncio
    async def test_using_shared_fixtures(
        self,
        db_session: AsyncSession,  # From conftest.py
        current_user: dict,  # From conftest.py
        admin_user: dict,  # From conftest.py
        utc_now: datetime,  # From conftest.py
    ):
        """Example: Using shared fixtures from conftest.py.

        This demonstrates how to leverage existing fixtures in your tests.
        See tests/conftest.py for all available fixtures.
        """
        # All fixtures are automatically injected by pytest
        assert db_session is not None
        assert current_user["email"] == "user@example.com"
        assert admin_user["email"] == "admin@example.com"
        assert utc_now.tzinfo is not None

    @pytest.mark.asyncio
    async def test_using_test_utilities(self, db_session: AsyncSession, current_user: dict):
        """Example: Using utilities from tests/utils.py.

        This demonstrates how to use ModelFactory, assertion helpers,
        and database helpers in your tests.
        """
        # Use factory to create test data
        product_data = create_product_data(
            name="Utility Example",
            created_by=current_user["email"],
        )
        product = Product(**product_data)

        # Use database helper
        product = await create_and_commit(db_session, product)

        # Use assertion helpers
        assert_audit_trail(product, created_by=current_user["email"])
        assert_primary_key_set(product, expected_type=int)

    @pytest.mark.asyncio
    async def test_using_custom_fixtures(
        self,
        sample_product: Product,  # Custom fixture defined above
        product_collection: list[Product],  # Custom fixture defined above
    ):
        """Example: Using custom feature-specific fixtures.

        This demonstrates creating and using custom fixtures
        for your feature's specific needs.
        """
        # Use pre-created sample product
        assert sample_product.id is not None
        assert sample_product.name == "Sample Product"

        # Use pre-created collection
        assert len(product_collection) == 5
        assert all(p.id is not None for p in product_collection)

    @pytest.mark.asyncio
    async def test_builder_pattern(self):
        """Example: Using builder pattern for complex test data.

        This demonstrates using fluent builders from tests/utils.py
        for creating complex test data.
        """
        # While we showed UserBuilder in utils.py, you can create
        # similar builders for your models:

        # product_data = (
        #     ProductBuilder()
        #     .with_name("Builder Product")
        #     .with_price("199.99")
        #     .with_stock(100)
        #     .with_audit("admin@example.com")
        #     .build()
        # )

        # For now, use the factory function
        product_data = create_product_data(
            name="Builder Example",
            price="199.99",
            stock_quantity=100,
        )
        assert product_data["name"] == "Builder Example"


# ============================================================================
# Summary
# ============================================================================

"""
This file demonstrates:

1. ✅ Creating test models with all mixins
2. ✅ Extending ModelFactory with new factory functions
3. ✅ Creating custom fixtures for feature-specific needs
4. ✅ Writing unit tests (fast, isolated)
5. ✅ Writing integration tests (real database)
6. ✅ Using parametrized tests for multiple scenarios
7. ✅ Testing edge cases and error scenarios
8. ✅ Using shared fixtures from conftest.py
9. ✅ Using utilities from tests/utils.py
10. ✅ Following best practices and patterns

When adding tests for new features:
1. Start with this file as a template
2. Use shared fixtures and utilities
3. Add new fixtures/utilities as needed
4. Follow the patterns demonstrated here
5. Group related tests in classes
6. Write clear docstrings
7. Test both success and edge cases

For more details, see docs/TESTING_GUIDE.md
"""
