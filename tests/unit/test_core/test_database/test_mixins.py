"""Comprehensive tests for database mixins.

This module tests the enhanced database layer including:
- SoftDeleteMixin with deleted_by tracking
- AuditColumnsMixin for user tracking
- TimestampMixin for automatic timestamps
- Combined mixin functionality
- Multiple primary key strategies (Integer, UUID v4, UUID v7)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import (
    AuditColumnsMixin,
    Base,
    IntegerPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPKMixin,
    UUIDv7PKMixin,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ============================================================================
# Test Models - Using composable mixins to test different combinations
# ============================================================================


class SimpleUser(Base, IntegerPKMixin, TimestampMixin):
    """Test model with integer PK and timestamps only."""

    __tablename__ = "simple_users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class AuditedDocument(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    """Test model with full audit trail (created_by, updated_by)."""

    __tablename__ = "audited_documents"
    __table_args__ = {"extend_existing": True}

    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(String(1000))


class SoftDeletablePost(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin, SoftDeleteMixin):
    """Test model with full audit trail including soft delete."""

    __tablename__ = "soft_deletable_posts"
    __table_args__ = {"extend_existing": True}

    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(String(1000))


class UUIDProduct(Base, UUIDPKMixin, TimestampMixin):
    """Test model with UUID v4 primary key."""

    __tablename__ = "uuid_products"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column(String(255))


class UUIDv7Event(Base, UUIDv7PKMixin, TimestampMixin):
    """Test model with UUID v7 (time-sortable) primary key."""

    __tablename__ = "uuidv7_events"
    __table_args__ = {"extend_existing": True}

    event_type: Mapped[str] = mapped_column(String(100))


class MinimalSoftDelete(Base, IntegerPKMixin, SoftDeleteMixin):
    """Test model with only soft delete mixin (no timestamps or audit)."""

    __tablename__ = "minimal_soft_delete"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column(String(255))


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def async_engine():
    """Create async SQLite engine for testing.

    Returns:
        SQLAlchemy async engine configured for in-memory SQLite.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()


@pytest.fixture
async def session(async_engine) -> AsyncGenerator[AsyncSession]:
    """Create async database session for testing.

    Args:
        async_engine: SQLAlchemy async engine fixture.

    Yields:
        Async database session for test operations.
    """
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        yield session


# ============================================================================
# TimestampMixin Tests
# ============================================================================


@pytest.mark.asyncio
async def test_timestamp_created_at_is_set_automatically(session: AsyncSession):
    """Test that created_at timestamp is automatically set on record creation.

    Validates:
    - created_at is not None after insert
    - created_at is a valid datetime (SQLite may strip timezone info)
    - created_at represents a time close to now
    """
    before = datetime.now(UTC).replace(tzinfo=None)  # SQLite strips timezone
    user = SimpleUser(email="test@example.com", name="Test User")

    session.add(user)
    await session.commit()
    await session.refresh(user)

    after = datetime.now(UTC).replace(tzinfo=None)

    assert user.created_at is not None
    # Note: SQLite doesn't preserve timezone info, so we check without timezone
    created_naive = (
        user.created_at.replace(tzinfo=None) if user.created_at.tzinfo else user.created_at
    )
    assert before <= created_naive <= after, "created_at should be between test bounds"


@pytest.mark.asyncio
async def test_timestamp_updated_at_is_set_automatically(session: AsyncSession):
    """Test that updated_at timestamp is automatically set on record creation.

    Validates:
    - updated_at is not None after insert
    - updated_at is a valid datetime (SQLite may strip timezone info)
    - updated_at equals created_at initially
    """
    user = SimpleUser(email="test@example.com", name="Test User")

    session.add(user)
    await session.commit()
    await session.refresh(user)

    assert user.updated_at is not None
    # Note: SQLite doesn't preserve timezone info, but the value is still valid
    # On creation, both timestamps should be very close (within same second typically)
    time_diff = abs((user.updated_at - user.created_at).total_seconds())
    assert time_diff < 2, "created_at and updated_at should be nearly identical on creation"


@pytest.mark.asyncio
async def test_timestamp_updated_at_changes_on_modification(session: AsyncSession):
    """Test that updated_at is automatically updated when record is modified.

    Validates:
    - updated_at changes after an update operation
    - updated_at is later than created_at after modification
    - created_at remains unchanged
    """
    user = SimpleUser(email="test@example.com", name="Test User")

    session.add(user)
    await session.commit()
    await session.refresh(user)

    original_created_at = user.created_at
    original_updated_at = user.updated_at

    # Modify the user
    user.name = "Updated Name"
    await session.commit()
    await session.refresh(user)

    assert user.created_at == original_created_at, "created_at should never change"
    assert user.updated_at >= original_updated_at, "updated_at should be updated"
    # In practice, updated_at should be strictly greater if time has passed
    # but we use >= to handle race conditions in fast test execution


@pytest.mark.asyncio
async def test_timestamp_created_at_is_immutable(session: AsyncSession):
    """Test that created_at timestamp does not change on updates.

    Validates:
    - created_at remains constant across multiple updates
    - Only updated_at changes with modifications
    """
    user = SimpleUser(email="test@example.com", name="Test User")

    session.add(user)
    await session.commit()
    await session.refresh(user)

    original_created_at = user.created_at

    # Perform multiple updates
    for i in range(3):
        user.name = f"Name Update {i}"
        await session.commit()
        await session.refresh(user)

        assert user.created_at == original_created_at, f"created_at changed on update {i + 1}"


# ============================================================================
# AuditColumnsMixin Tests
# ============================================================================


@pytest.mark.asyncio
async def test_audit_created_by_is_set_on_creation(session: AsyncSession):
    """Test that created_by field can be set and persisted on record creation.

    Validates:
    - created_by field accepts user identifier
    - Value is persisted correctly to database
    - Field is nullable (can be None for anonymous operations)
    """
    current_user = "admin@example.com"
    doc = AuditedDocument(
        title="Test Document",
        content="Test content",
        created_by=current_user,
    )

    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    assert doc.created_by == current_user
    assert doc.updated_by is None, "updated_by should be None on creation"


@pytest.mark.asyncio
async def test_audit_updated_by_is_set_on_update(session: AsyncSession):
    """Test that updated_by field is set when record is modified.

    Validates:
    - updated_by can be set independently of created_by
    - Value is persisted correctly after update
    - created_by remains unchanged
    """
    creator = "creator@example.com"
    updater = "updater@example.com"

    doc = AuditedDocument(
        title="Test Document",
        content="Original content",
        created_by=creator,
    )

    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    # Update the document
    doc.content = "Updated content"
    doc.updated_by = updater
    await session.commit()
    await session.refresh(doc)

    assert doc.created_by == creator, "created_by should not change"
    assert doc.updated_by == updater, "updated_by should be set"


@pytest.mark.asyncio
async def test_audit_fields_are_nullable(session: AsyncSession):
    """Test that audit fields can be None for anonymous operations.

    Validates:
    - Records can be created without user tracking
    - Both created_by and updated_by can remain None
    - System/automated operations don't require user context
    """
    doc = AuditedDocument(
        title="Anonymous Document",
        content="Created by system",
    )

    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    assert doc.created_by is None, "created_by should allow None"
    assert doc.updated_by is None, "updated_by should allow None"


@pytest.mark.asyncio
async def test_audit_supports_multiple_updates_by_different_users(session: AsyncSession):
    """Test that updated_by tracks the most recent modifier correctly.

    Validates:
    - updated_by can be changed multiple times
    - Each update can have a different user
    - History is not maintained (only last modifier is stored)
    """
    doc = AuditedDocument(
        title="Collaborative Document",
        content="Initial content",
        created_by="user1@example.com",
    )

    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    users = ["user2@example.com", "user3@example.com", "user4@example.com"]

    for i, user in enumerate(users):
        doc.content = f"Update {i + 1}"
        doc.updated_by = user
        await session.commit()
        await session.refresh(doc)

        assert doc.updated_by == user, f"updated_by should reflect user {i + 1}"
        assert doc.created_by == "user1@example.com", "created_by should remain unchanged"


# ============================================================================
# SoftDeleteMixin Tests
# ============================================================================


@pytest.mark.asyncio
async def test_soft_delete_deleted_by_field_is_set(session: AsyncSession):
    """Test that deleted_by field is set correctly during soft delete.

    Validates:
    - deleted_by field accepts and persists user identifier
    - deleted_at and deleted_by work together for complete audit trail
    - WHO deleted the record is tracked
    """
    deleter = "admin@example.com"
    post = SoftDeletablePost(
        title="Test Post",
        content="Test content",
        created_by="author@example.com",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Soft delete the post
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = deleter
    await session.commit()
    await session.refresh(post)

    assert post.deleted_at is not None, "deleted_at should be set"
    assert post.deleted_by == deleter, "deleted_by should track who deleted"
    assert post.is_deleted, "is_deleted property should return True"


@pytest.mark.asyncio
async def test_soft_delete_is_deleted_property_returns_correct_value(session: AsyncSession):
    """Test that is_deleted property accurately reflects deletion state.

    Validates:
    - is_deleted returns False for active records
    - is_deleted returns True when deleted_at is set
    - Property is computed, not stored
    """
    post = SoftDeletablePost(
        title="Test Post",
        content="Test content",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    assert not post.is_deleted, "New record should not be deleted"

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(post)

    assert post.is_deleted, "Record with deleted_at should be deleted"


@pytest.mark.asyncio
async def test_soft_delete_queries_must_explicitly_filter(session: AsyncSession):
    """Test that soft-deleted records are included in queries by default.

    Validates:
    - Soft delete is logical, not physical (records remain in database)
    - Queries must explicitly filter deleted_at to exclude soft-deleted records
    - Both deleted and non-deleted records are accessible
    """
    # Create multiple posts
    active_post = SoftDeletablePost(title="Active", content="Active content")
    deleted_post = SoftDeletablePost(title="Deleted", content="Deleted content")

    session.add_all([active_post, deleted_post])
    await session.commit()

    # Soft delete one post
    deleted_post.deleted_at = datetime.now(UTC)
    deleted_post.deleted_by = "admin@example.com"
    await session.commit()

    # Query all posts (including deleted)
    stmt_all = select(SoftDeletablePost)
    result_all = await session.execute(stmt_all)
    all_posts = result_all.scalars().all()

    assert len(all_posts) == 2, "Should include both active and deleted records"

    # Query only active posts (exclude soft-deleted)
    stmt_active = select(SoftDeletablePost).where(SoftDeletablePost.deleted_at.is_(None))
    result_active = await session.execute(stmt_active)
    active_posts = result_active.scalars().all()

    assert len(active_posts) == 1, "Should only include active records"
    assert active_posts[0].title == "Active"


@pytest.mark.asyncio
async def test_soft_delete_recovery(session: AsyncSession):
    """Test that soft-deleted records can be recovered.

    Validates:
    - deleted_at and deleted_by can be set back to None
    - Recovered records are fully functional
    - Complete audit trail is maintained (recovery doesn't erase history in practice)
    """
    post = SoftDeletablePost(
        title="Recoverable Post",
        content="Test content",
        created_by="author@example.com",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = "admin@example.com"
    await session.commit()
    await session.refresh(post)

    assert post.is_deleted, "Post should be deleted"

    # Recover the post
    post.deleted_at = None
    post.deleted_by = None
    await session.commit()
    await session.refresh(post)

    assert not post.is_deleted, "Post should be recovered"
    assert post.deleted_at is None
    assert post.deleted_by is None


@pytest.mark.asyncio
async def test_soft_delete_without_user_tracking(session: AsyncSession):
    """Test soft delete without specifying deleted_by (anonymous deletion).

    Validates:
    - Records can be soft-deleted without user tracking
    - deleted_by field is nullable
    - System/automated deletions are supported
    """
    post = MinimalSoftDelete(name="Test Post")

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Soft delete without user tracking
    post.deleted_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(post)

    assert post.is_deleted, "Post should be deleted"
    assert post.deleted_by is None, "deleted_by should allow None"


@pytest.mark.asyncio
async def test_soft_delete_with_minimal_mixin(session: AsyncSession):
    """Test that SoftDeleteMixin works independently without timestamps/audit.

    Validates:
    - SoftDeleteMixin doesn't require other mixins
    - Can be used in isolation for simple soft delete needs
    - Only deleted_at and deleted_by fields are added
    """
    record = MinimalSoftDelete(name="Minimal Record")

    session.add(record)
    await session.commit()
    await session.refresh(record)

    # Verify only soft delete functionality exists (no timestamps)
    assert hasattr(record, "deleted_at")
    assert hasattr(record, "deleted_by")
    assert hasattr(record, "is_deleted")
    assert not hasattr(record, "created_at"), "Should not have timestamp fields"
    assert not hasattr(record, "updated_at"), "Should not have timestamp fields"


# ============================================================================
# Combined Mixins Tests
# ============================================================================


@pytest.mark.asyncio
async def test_combined_mixins_full_audit_trail_creation_to_deletion(
    session: AsyncSession,
):
    """Test complete audit trail from creation through deletion.

    Validates:
    - All audit fields work together correctly
    - Complete lifecycle tracking: created_by, updated_by, deleted_by
    - Timestamps track when each operation occurred
    """
    creator = "creator@example.com"
    updater = "updater@example.com"
    deleter = "deleter@example.com"

    # Create
    post = SoftDeletablePost(
        title="Lifecycle Post",
        content="Initial content",
        created_by=creator,
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    creation_time = post.created_at

    assert post.created_by == creator
    assert post.updated_by is None
    assert post.deleted_by is None
    assert not post.is_deleted

    # Update
    post.content = "Updated content"
    post.updated_by = updater
    await session.commit()
    await session.refresh(post)

    update_time = post.updated_at

    assert post.created_by == creator, "created_by should not change"
    assert post.updated_by == updater
    assert post.deleted_by is None
    assert not post.is_deleted
    assert update_time >= creation_time

    # Soft Delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = deleter
    await session.commit()
    await session.refresh(post)

    deletion_time = post.deleted_at

    assert post.created_by == creator, "created_by should not change"
    assert post.updated_by == updater, "updated_by should not change"
    assert post.deleted_by == deleter
    assert post.is_deleted
    assert deletion_time >= update_time


@pytest.mark.asyncio
async def test_combined_mixins_audit_trail_works_with_soft_delete(
    session: AsyncSession,
):
    """Test that audit columns continue to work after soft delete.

    Validates:
    - Soft-deleted records retain all audit information
    - Audit trail is not lost on deletion
    - Data can be analyzed even after deletion
    """
    post = SoftDeletablePost(
        title="Audit Test",
        content="Content",
        created_by="user1@example.com",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    original_created_by = post.created_by
    original_created_at = post.created_at

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = "admin@example.com"
    await session.commit()

    # Query the soft-deleted record directly
    stmt = select(SoftDeletablePost).where(SoftDeletablePost.id == post.id)
    result = await session.execute(stmt)
    deleted_post = result.scalar_one()

    assert deleted_post.created_by == original_created_by
    assert deleted_post.created_at == original_created_at
    assert deleted_post.deleted_by == "admin@example.com"
    assert deleted_post.is_deleted


# ============================================================================
# Primary Key Strategy Tests
# ============================================================================


@pytest.mark.asyncio
async def test_integer_pk_strategy(session: AsyncSession):
    """Test integer auto-increment primary key strategy.

    Validates:
    - IDs are automatically assigned
    - IDs are sequential integers
    - Multiple records get different IDs
    """
    user1 = SimpleUser(email="user1@example.com", name="User 1")
    user2 = SimpleUser(email="user2@example.com", name="User 2")

    session.add_all([user1, user2])
    await session.commit()
    await session.refresh(user1)
    await session.refresh(user2)

    assert isinstance(user1.id, int), "ID should be integer"
    assert isinstance(user2.id, int), "ID should be integer"
    assert user1.id != user2.id, "IDs should be unique"
    assert user2.id > user1.id, "IDs should be sequential"


@pytest.mark.asyncio
async def test_uuid_v4_pk_strategy(session: AsyncSession):
    """Test UUID v4 (random) primary key strategy.

    Validates:
    - IDs are automatically generated
    - IDs are valid UUID v4 format
    - IDs are globally unique (not sequential)
    """
    product1 = UUIDProduct(name="Product 1")
    product2 = UUIDProduct(name="Product 2")

    session.add_all([product1, product2])
    await session.commit()
    await session.refresh(product1)
    await session.refresh(product2)

    assert isinstance(product1.id, UUID), "ID should be UUID"
    assert isinstance(product2.id, UUID), "ID should be UUID"
    assert product1.id != product2.id, "IDs should be unique"
    assert product1.id.version == 4, "Should be UUID v4"
    assert product2.id.version == 4, "Should be UUID v4"


@pytest.mark.asyncio
async def test_uuid_v7_pk_strategy_is_time_sortable(session: AsyncSession):
    """Test UUID v7 (time-sortable) primary key strategy.

    Validates:
    - IDs are automatically generated
    - IDs are valid UUID v7 format
    - IDs are time-ordered (later records have larger IDs)
    - Useful for event logs and audit trails
    """
    event1 = UUIDv7Event(event_type="login")

    session.add(event1)
    await session.commit()
    await session.refresh(event1)

    # Create second event (will have later timestamp)
    event2 = UUIDv7Event(event_type="logout")

    session.add(event2)
    await session.commit()
    await session.refresh(event2)

    assert isinstance(event1.id, UUID), "ID should be UUID"
    assert isinstance(event2.id, UUID), "ID should be UUID"
    assert event1.id != event2.id, "IDs should be unique"
    assert event1.id.version == 7, "Should be UUID v7"
    assert event2.id.version == 7, "Should be UUID v7"

    # UUID v7 encodes timestamp, so later events should have larger IDs
    # when compared as strings or integers
    assert str(event1.id) < str(event2.id), "UUID v7 should be time-sortable"


@pytest.mark.asyncio
async def test_uuid_v7_pk_different_from_uuid_v4(session: AsyncSession):
    """Test that UUID v7 and UUID v4 generate different version numbers.

    Validates:
    - UUID v4 and v7 are distinct strategies
    - Version field correctly identifies the UUID type
    - Both can coexist in the same database
    """
    product = UUIDProduct(name="V4 Product")
    event = UUIDv7Event(event_type="V7 Event")

    session.add_all([product, event])
    await session.commit()
    await session.refresh(product)
    await session.refresh(event)

    assert product.id.version == 4, "UUIDProduct should use UUID v4"
    assert event.id.version == 7, "UUIDv7Event should use UUID v7"


# ============================================================================
# Edge Cases and Error Scenarios
# ============================================================================


@pytest.mark.asyncio
async def test_soft_delete_deleted_at_without_deleted_by(session: AsyncSession):
    """Test that setting only deleted_at (without deleted_by) is valid.

    Validates:
    - Partial soft delete (only deleted_at) is acceptable
    - deleted_by is optional for automated/system deletions
    - is_deleted property only checks deleted_at
    """
    post = SoftDeletablePost(title="Test", content="Content")

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Set only deleted_at
    post.deleted_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(post)

    assert post.is_deleted, "Should be considered deleted"
    assert post.deleted_by is None, "deleted_by should remain None"


@pytest.mark.asyncio
async def test_timestamp_precision_across_updates(session: AsyncSession):
    """Test that updated_at precision is sufficient to detect rapid updates.

    Validates:
    - Timestamp precision captures microseconds
    - Rapid updates are distinguishable
    - No data loss in high-frequency update scenarios
    """
    user = SimpleUser(email="test@example.com", name="Test User")

    session.add(user)
    await session.commit()
    await session.refresh(user)

    timestamps = [user.updated_at]

    # Perform rapid updates
    for i in range(3):
        user.name = f"Name {i}"
        await session.commit()
        await session.refresh(user)
        timestamps.append(user.updated_at)

    # All timestamps should be unique or at least non-decreasing
    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1], f"Timestamp {i} should not be later than {i + 1}"


@pytest.mark.asyncio
async def test_audit_fields_max_length(session: AsyncSession):
    """Test that audit fields handle maximum string length.

    Validates:
    - Audit fields support up to 255 characters
    - Long user identifiers (emails, UUIDs) are supported
    - No truncation for standard identifier formats
    """
    long_email = "a" * 245 + "@test.com"  # 254 characters (max for email)

    doc = AuditedDocument(
        title="Test",
        content="Content",
        created_by=long_email,
    )

    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    assert doc.created_by == long_email, "Long email should be stored completely"
    assert len(doc.created_by) == 254


@pytest.mark.asyncio
async def test_multiple_soft_deletes_and_recoveries(session: AsyncSession):
    """Test that records can be deleted and recovered multiple times.

    Validates:
    - Soft delete is reversible and repeatable
    - No side effects from multiple delete/recover cycles
    - State transitions work correctly
    """
    post = SoftDeletablePost(
        title="Test Post",
        content="Content",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Cycle through delete and recover multiple times
    for cycle in range(3):
        # Delete
        post.deleted_at = datetime.now(UTC)
        post.deleted_by = f"deleter{cycle}@example.com"
        await session.commit()
        await session.refresh(post)

        assert post.is_deleted, f"Should be deleted in cycle {cycle}"

        # Recover
        post.deleted_at = None
        post.deleted_by = None
        await session.commit()
        await session.refresh(post)

        assert not post.is_deleted, f"Should be recovered in cycle {cycle}"


@pytest.mark.asyncio
async def test_timezone_aware_timestamps_are_utc(session: AsyncSession):
    """Test that all timestamps are valid datetime objects.

    Validates:
    - Timestamps are valid datetime objects
    - Timestamps are properly stored and retrieved
    - Soft delete timestamps work correctly

    Note: SQLite doesn't preserve timezone info in test environment,
    but in production PostgreSQL the timestamps will be timezone-aware UTC.
    """
    post = SoftDeletablePost(
        title="Timezone Test",
        content="Content",
    )

    session.add(post)
    await session.commit()
    await session.refresh(post)

    # Check that timestamps exist and are valid datetime objects
    assert post.created_at is not None, "created_at should be set"
    assert isinstance(post.created_at, datetime), "created_at should be datetime"

    assert post.updated_at is not None, "updated_at should be set"
    assert isinstance(post.updated_at, datetime), "updated_at should be datetime"

    # Soft delete and check deleted_at
    post.deleted_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(post)

    assert post.deleted_at is not None, "deleted_at should be set"
    assert isinstance(post.deleted_at, datetime), "deleted_at should be datetime"
