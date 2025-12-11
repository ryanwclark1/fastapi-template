"""Test utilities and helper functions.

This module provides reusable utilities for creating test data and performing
common test operations. These utilities make tests more maintainable and reduce
code duplication.

Usage:
    from tests.utils import ModelFactory, assert_audit_trail, assert_soft_deleted

    # Create test models
    user = ModelFactory.create_user(email="test@example.com")

    # Assert audit trail
    assert_audit_trail(user, created_by="user@example.com")

    # Assert soft delete
    assert_soft_deleted(user, deleted_by="admin@example.com")
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from example_service.utils.runtime_dependencies import require_runtime_dependency

if TYPE_CHECKING:
    from example_service.core.database.base import Base

require_runtime_dependency(datetime)


# ============================================================================
# Model Factories - Create test models with realistic data
# ============================================================================


class ModelFactory:
    """Factory for creating test model instances with realistic defaults.

    This class provides static methods for creating common test models.
    Each method returns a dictionary that can be used to create a model instance.

    Example:
        user_data = ModelFactory.create_user()
        user = User(**user_data)

        # Or with custom fields
        admin_data = ModelFactory.create_user(
            email="admin@example.com",
            name="Admin User"
        )
    """

    @staticmethod
    def create_user(
        email: str | None = None,
        name: str | None = None,
        created_by: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create user model data with defaults.

        Args:
            email: User email (defaults to test@example.com)
            name: User name (defaults to Test User)
            created_by: Creator email for audit tracking
            **kwargs: Additional fields to include

        Returns:
            Dictionary with user data
        """
        data = {
            "email": email or "test@example.com",
            "name": name or "Test User",
        }
        if created_by:
            data["created_by"] = created_by
        data.update(kwargs)
        return data

    @staticmethod
    def create_document(
        title: str | None = None,
        content: str | None = None,
        created_by: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create document model data with defaults.

        Args:
            title: Document title
            content: Document content
            created_by: Creator email for audit tracking
            **kwargs: Additional fields

        Returns:
            Dictionary with document data
        """
        data = {
            "title": title or "Test Document",
            "content": content or "This is test content.",
        }
        if created_by:
            data["created_by"] = created_by
        data.update(kwargs)
        return data

    @staticmethod
    def create_post(
        title: str | None = None,
        content: str | None = None,
        created_by: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create post model data with defaults.

        Args:
            title: Post title
            content: Post content
            created_by: Creator email for audit tracking
            **kwargs: Additional fields

        Returns:
            Dictionary with post data
        """
        data = {
            "title": title or "Test Post",
            "content": content or "This is a test post.",
        }
        if created_by:
            data["created_by"] = created_by
        data.update(kwargs)
        return data

    @staticmethod
    def create_batch(
        factory_method: callable,
        count: int,
        created_by: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Create multiple model instances using a factory method.

        Args:
            factory_method: Factory method to call (e.g., ModelFactory.create_user)
            count: Number of instances to create
            created_by: Creator email for audit tracking
            **kwargs: Additional fields passed to factory method

        Returns:
            List of model data dictionaries

        Example:
            users = ModelFactory.create_batch(
                ModelFactory.create_user,
                count=5,
                created_by="admin@example.com"
            )
        """
        return [
            factory_method(
                created_by=created_by,
                **kwargs,
            )
            for _ in range(count)
        ]


# ============================================================================
# Assertion Helpers - Reusable assertion functions
# ============================================================================


def assert_audit_trail(
    model: Base,
    created_by: str | None = None,
    updated_by: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    """Assert that audit trail fields are set correctly.

    Args:
        model: Model instance to check
        created_by: Expected created_by value (if provided)
        updated_by: Expected updated_by value (if provided)
        created_at: Expected created_at value (if provided)
        updated_at: Expected updated_at value (if provided)

    Raises:
        AssertionError: If any audit field doesn't match expected value

    Example:
        user = User(email="test@example.com")
        user.created_by = "admin@example.com"
        assert_audit_trail(user, created_by="admin@example.com")
    """
    # Check timestamp fields if model has them
    if hasattr(model, "created_at"):
        assert model.created_at is not None, "created_at should be set"
        # Note: SQLite stores timestamps without timezone info, PostgreSQL preserves it
        # We only verify the datetime exists and is valid
        if created_at:
            assert model.created_at == created_at, (
                f"Expected created_at={created_at}, got {model.created_at}"
            )

    if hasattr(model, "updated_at"):
        assert model.updated_at is not None, "updated_at should be set"
        # Note: SQLite stores timestamps without timezone info, PostgreSQL preserves it
        # We only verify the datetime exists and is valid
        if updated_at:
            assert model.updated_at == updated_at, (
                f"Expected updated_at={updated_at}, got {model.updated_at}"
            )

    # Check audit user fields if model has them
    if hasattr(model, "created_by") and created_by is not None:
        assert model.created_by == created_by, (
            f"Expected created_by={created_by}, got {model.created_by}"
        )

    if hasattr(model, "updated_by") and updated_by is not None:
        assert model.updated_by == updated_by, (
            f"Expected updated_by={updated_by}, got {model.updated_by}"
        )


def assert_soft_deleted(
    model: Base,
    deleted_by: str | None = None,
    is_deleted: bool = True,
) -> None:
    """Assert that soft delete fields are set correctly.

    Args:
        model: Model instance to check
        deleted_by: Expected deleted_by value (if provided)
        is_deleted: Expected deleted state (default True)

    Raises:
        AssertionError: If soft delete state doesn't match expected

    Example:
        post = Post(title="Test")
        post.deleted_at = datetime.now(UTC)
        post.deleted_by = "admin@example.com"
        assert_soft_deleted(post, deleted_by="admin@example.com")
    """
    if not hasattr(model, "deleted_at"):
        msg = f"{model.__class__.__name__} does not have soft delete support"
        raise AttributeError(msg)

    if is_deleted:
        assert model.deleted_at is not None, "deleted_at should be set for soft-deleted record"
        # Note: SQLite stores timestamps without timezone info, PostgreSQL preserves it
        # We only verify the datetime exists and is valid
        assert model.is_deleted, "is_deleted property should return True"

        if hasattr(model, "deleted_by") and deleted_by is not None:
            assert model.deleted_by == deleted_by, (
                f"Expected deleted_by={deleted_by}, got {model.deleted_by}"
            )
    else:
        assert model.deleted_at is None, "deleted_at should be None for non-deleted record"
        assert not model.is_deleted, "is_deleted property should return False"

        if hasattr(model, "deleted_by"):
            assert model.deleted_by is None, "deleted_by should be None for non-deleted record"


def assert_timestamps_updated(
    model: Base,
    original_updated_at: datetime,
) -> None:
    """Assert that updated_at timestamp has changed.

    Args:
        model: Model instance to check
        original_updated_at: Original updated_at value before update

    Raises:
        AssertionError: If updated_at hasn't changed

    Example:
        user = await session.get(User, 1)
        original = user.updated_at

        user.name = "New Name"
        await session.commit()
        await session.refresh(user)

        assert_timestamps_updated(user, original)
    """
    if not hasattr(model, "updated_at"):
        msg = f"{model.__class__.__name__} does not have updated_at field"
        raise AttributeError(msg)

    assert model.updated_at > original_updated_at, (
        f"updated_at should have changed. Original: {original_updated_at}, Current: {model.updated_at}"
    )


def assert_primary_key_set(model: Base, expected_type: type | None = None) -> None:
    """Assert that primary key is set and has correct type.

    Args:
        model: Model instance to check
        expected_type: Expected type of primary key (int, UUID, etc.)

    Raises:
        AssertionError: If primary key is not set or has wrong type

    Example:
        user = User(email="test@example.com")
        session.add(user)
        await session.commit()

        assert_primary_key_set(user, expected_type=int)
    """
    assert hasattr(model, "id"), f"{model.__class__.__name__} should have 'id' attribute"
    assert model.id is not None, "Primary key should be set"

    if expected_type:
        assert isinstance(model.id, expected_type), (
            f"Primary key should be {expected_type.__name__}, got {type(model.id).__name__}"
        )


# ============================================================================
# Database Test Helpers
# ============================================================================


async def create_and_commit(session: Any, model: Base) -> Base:
    """Create model instance and commit to database.

    Args:
        session: Database session
        model: Model instance to create

    Returns:
        Created model with ID populated

    Example:
        user = User(email="test@example.com")
        user = await create_and_commit(session, user)
        assert user.id is not None
    """
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


async def create_batch_and_commit(session: Any, models: list[Base]) -> list[Base]:
    """Create multiple model instances and commit to database.

    Args:
        session: Database session
        models: List of model instances to create

    Returns:
        List of created models with IDs populated

    Example:
        users = [User(email=f"user{i}@example.com") for i in range(5)]
        users = await create_batch_and_commit(session, users)
        assert all(u.id is not None for u in users)
    """
    session.add_all(models)
    await session.commit()
    for model in models:
        await session.refresh(model)
    return models


# ============================================================================
# Cache Test Helpers
# ============================================================================


class CacheTestHelper:
    """Helper class for testing cache operations.

    Example:
        helper = CacheTestHelper(mock_redis_client)
        await helper.set("key", "value")
        assert await helper.exists("key")
        await helper.clear()
    """

    def __init__(self, redis_client):
        """Initialize with Redis client (mock or real).

        Args:
            redis_client: Redis client instance
        """
        self.client = redis_client
        self._storage: dict[str, Any] = {}

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set cache value.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds
        """
        self._storage[key] = value
        await self.client.set(key, value, ex=ttl)

    async def get(self, key: str) -> Any | None:
        """Get cache value.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        return self._storage.get(key)

    async def delete(self, key: str) -> bool:
        """Delete cache value.

        Args:
            key: Cache key

        Returns:
            True if key existed
        """
        if key in self._storage:
            del self._storage[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Cache key

        Returns:
            True if key exists
        """
        return key in self._storage

    async def clear(self) -> None:
        """Clear all cache entries."""
        self._storage.clear()


# ============================================================================
# Test Data Builders - Fluent interface for building test data
# ============================================================================


class UserBuilder:
    """Fluent builder for creating user test data.

    Example:
        user_data = (
            UserBuilder()
            .with_email("test@example.com")
            .with_name("Test User")
            .with_audit("admin@example.com")
            .build()
        )
    """

    def __init__(self):
        """Initialize builder with default values."""
        self._data = {
            "email": "test@example.com",
            "name": "Test User",
        }

    def with_email(self, email: str) -> UserBuilder:
        """Set email.

        Args:
            email: User email

        Returns:
            Self for chaining
        """
        self._data["email"] = email
        return self

    def with_name(self, name: str) -> UserBuilder:
        """Set name.

        Args:
            name: User name

        Returns:
            Self for chaining
        """
        self._data["name"] = name
        return self

    def with_audit(self, created_by: str) -> UserBuilder:
        """Set audit tracking.

        Args:
            created_by: Creator email

        Returns:
            Self for chaining
        """
        self._data["created_by"] = created_by
        return self

    def build(self) -> dict[str, Any]:
        """Build user data dictionary.

        Returns:
            Dictionary with user data
        """
        return self._data.copy()


class DocumentBuilder:
    """Fluent builder for creating document test data.

    Example:
        doc_data = (
            DocumentBuilder()
            .with_title("My Document")
            .with_content("Content here")
            .with_audit("user@example.com")
            .build()
        )
    """

    def __init__(self):
        """Initialize builder with default values."""
        self._data = {
            "title": "Test Document",
            "content": "This is test content.",
        }

    def with_title(self, title: str) -> DocumentBuilder:
        """Set title.

        Args:
            title: Document title

        Returns:
            Self for chaining
        """
        self._data["title"] = title
        return self

    def with_content(self, content: str) -> DocumentBuilder:
        """Set content.

        Args:
            content: Document content

        Returns:
            Self for chaining
        """
        self._data["content"] = content
        return self

    def with_audit(self, created_by: str) -> DocumentBuilder:
        """Set audit tracking.

        Args:
            created_by: Creator email

        Returns:
            Self for chaining
        """
        self._data["created_by"] = created_by
        return self

    def build(self) -> dict[str, Any]:
        """Build document data dictionary.

        Returns:
            Dictionary with document data
        """
        return self._data.copy()


__all__ = [
    # Cache helpers
    "CacheTestHelper",
    "DocumentBuilder",
    # Factories
    "ModelFactory",
    # Builders
    "UserBuilder",
    # Assertions
    "assert_audit_trail",
    "assert_primary_key_set",
    "assert_soft_deleted",
    "assert_timestamps_updated",
    # Database helpers
    "create_and_commit",
    "create_batch_and_commit",
]
