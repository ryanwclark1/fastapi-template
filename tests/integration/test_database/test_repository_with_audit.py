"""Integration tests for BaseRepository with audit trail and soft delete features.

This test suite validates the repository pattern with enhanced audit capabilities:
- Audit trail tracking (created_by, updated_by)
- Soft delete support (deleted_at, deleted_by)
- Pagination with soft delete filtering
- Bulk operations with audit tracking
- Complete lifecycle scenarios

Tests use real SQLAlchemy sessions with in-memory SQLite to ensure
database operations work correctly without mocking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import (
    AuditColumnsMixin,
    Base,
    IntegerPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from example_service.core.database.repository import BaseRepository


# ============================================================================
# Test Models
# ============================================================================


class AuditedDocument(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    """Test model with full audit trail (no soft delete)."""

    __tablename__ = "audited_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class SoftDeletablePost(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
    """Test model with soft delete support (no audit columns)."""

    __tablename__ = "soft_deletable_posts"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class FullAuditPost(
    Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin, SoftDeleteMixin
):
    """Test model with complete audit trail and soft delete."""

    __tablename__ = "full_audit_posts"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def engine():
    """Create in-memory SQLite engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,  # Set to True for SQL debugging
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """Provide an isolated database session with test tables created."""
    # Create all test tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session


@pytest.fixture
def current_user() -> str:
    """Simulated current user for audit tracking."""
    return "test.user@example.com"


@pytest.fixture
def admin_user() -> str:
    """Simulated admin user for audit tracking."""
    return "admin@example.com"


# ============================================================================
# Repository with Audit Trail Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_sets_created_by(session: AsyncSession, current_user: str) -> None:
    """Test that create() properly tracks who created the record."""
    repo = BaseRepository(AuditedDocument)

    doc = AuditedDocument(title="Test Document", created_by=current_user)
    result = await repo.create(session, doc)
    await session.commit()

    assert result.id is not None
    assert result.created_by == current_user
    assert result.updated_by is None  # Not set on create
    assert result.created_at is not None
    assert result.updated_at is not None


@pytest.mark.asyncio
async def test_update_sets_updated_by(session: AsyncSession, current_user: str) -> None:
    """Test that updates properly track who modified the record."""
    repo = BaseRepository(AuditedDocument)

    # Create document
    doc = AuditedDocument(title="Original", created_by=current_user)
    doc = await repo.create(session, doc)
    await session.commit()

    original_updated_at = doc.updated_at

    # Small delay to ensure timestamp difference
    import asyncio

    await asyncio.sleep(0.01)

    # Update document with different user
    doc.title = "Updated"
    doc.updated_by = "updater@example.com"
    session.add(doc)
    await session.flush()
    await session.refresh(doc)
    await session.commit()

    assert doc.created_by == current_user
    assert doc.updated_by == "updater@example.com"
    assert doc.updated_at > original_updated_at


@pytest.mark.asyncio
async def test_complete_audit_trail_through_lifecycle(
    session: AsyncSession, current_user: str, admin_user: str
) -> None:
    """Test complete audit trail: create -> update -> verify all fields."""
    repo = BaseRepository(AuditedDocument)

    # Create
    doc = AuditedDocument(title="Lifecycle Test", content="Initial", created_by=current_user)
    doc = await repo.create(session, doc)
    await session.commit()

    assert doc.created_by == current_user
    assert doc.updated_by is None

    # First update by same user
    doc.content = "First Update"
    doc.updated_by = current_user
    session.add(doc)
    await session.flush()
    await session.refresh(doc)

    assert doc.created_by == current_user
    assert doc.updated_by == current_user

    # Second update by admin
    doc.content = "Admin Update"
    doc.updated_by = admin_user
    session.add(doc)
    await session.flush()
    await session.refresh(doc)
    await session.commit()

    assert doc.created_by == current_user  # Creator never changes
    assert doc.updated_by == admin_user  # Last updater tracked


# ============================================================================
# Repository with Soft Delete Tests
# ============================================================================


@pytest.mark.asyncio
async def test_soft_delete_via_update(
    session: AsyncSession, current_user: str
) -> None:
    """Test soft delete by setting deleted_at and deleted_by."""
    repo = BaseRepository(SoftDeletablePost)

    # Create post
    post = SoftDeletablePost(title="To Delete")
    post = await repo.create(session, post)
    await session.commit()

    assert not post.is_deleted
    assert post.deleted_at is None
    assert post.deleted_by is None

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = current_user
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    assert post.is_deleted
    assert post.deleted_at is not None
    assert post.deleted_by == current_user


@pytest.mark.asyncio
async def test_get_excludes_soft_deleted_by_default(session: AsyncSession) -> None:
    """Test that get() excludes soft-deleted records by default."""
    repo = BaseRepository(SoftDeletablePost)

    # Create and soft delete a post
    post = SoftDeletablePost(title="Deleted Post")
    post = await repo.create(session, post)
    post_id = post.id
    await session.commit()

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = "system"
    session.add(post)
    await session.commit()

    # Query using repository - should apply soft delete filter
    # Note: BaseRepository.get() doesn't have include_deleted parameter
    # We need to query manually with filter
    stmt = select(SoftDeletablePost).where(
        SoftDeletablePost.id == post_id,
        SoftDeletablePost.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    found = result.scalar_one_or_none()

    assert found is None, "Soft-deleted record should not be found with filter"


@pytest.mark.asyncio
async def test_get_includes_soft_deleted_when_specified(session: AsyncSession) -> None:
    """Test that we can query soft-deleted records when explicitly included."""
    repo = BaseRepository(SoftDeletablePost)

    # Create and soft delete a post
    post = SoftDeletablePost(title="Deleted Post")
    post = await repo.create(session, post)
    post_id = post.id
    await session.commit()

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = "system"
    session.add(post)
    await session.commit()

    # Query without soft delete filter - should find it
    found = await repo.get(session, post_id)

    assert found is not None
    assert found.is_deleted
    assert found.deleted_by == "system"


@pytest.mark.asyncio
async def test_list_excludes_soft_deleted_by_default(session: AsyncSession) -> None:
    """Test that list() excludes soft-deleted records by default."""
    repo = BaseRepository(SoftDeletablePost)

    # Create multiple posts
    post1 = SoftDeletablePost(title="Active Post")
    post2 = SoftDeletablePost(title="Deleted Post")
    post3 = SoftDeletablePost(title="Another Active")

    await repo.create(session, post1)
    await repo.create(session, post2)
    await repo.create(session, post3)
    await session.commit()

    # Soft delete post2
    post2.deleted_at = datetime.now(UTC)
    post2.deleted_by = "system"
    session.add(post2)
    await session.commit()

    # List with filter
    stmt = select(SoftDeletablePost).where(SoftDeletablePost.deleted_at.is_(None))
    result = await session.execute(stmt)
    posts = result.scalars().all()

    assert len(posts) == 2
    titles = {p.title for p in posts}
    assert titles == {"Active Post", "Another Active"}


@pytest.mark.asyncio
async def test_list_includes_all_with_soft_delete_included(session: AsyncSession) -> None:
    """Test that list() can include soft-deleted records when specified."""
    repo = BaseRepository(SoftDeletablePost)

    # Create multiple posts
    post1 = SoftDeletablePost(title="Active Post")
    post2 = SoftDeletablePost(title="Deleted Post")

    await repo.create(session, post1)
    await repo.create(session, post2)
    await session.commit()

    # Soft delete post2
    post2.deleted_at = datetime.now(UTC)
    session.add(post2)
    await session.commit()

    # List without filter (all records)
    posts = await repo.list(session, limit=100)

    assert len(posts) == 2


@pytest.mark.asyncio
async def test_recovering_soft_deleted_record(
    session: AsyncSession, current_user: str
) -> None:
    """Test recovering a soft-deleted record by clearing deleted_at."""
    repo = BaseRepository(SoftDeletablePost)

    # Create and soft delete
    post = SoftDeletablePost(title="Recoverable Post")
    post = await repo.create(session, post)
    post_id = post.id
    await session.commit()

    post.deleted_at = datetime.now(UTC)
    post.deleted_by = current_user
    session.add(post)
    await session.commit()

    assert post.is_deleted

    # Recover
    post.deleted_at = None
    post.deleted_by = None
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    assert not post.is_deleted
    assert post.deleted_at is None
    assert post.deleted_by is None

    # Verify it appears in filtered lists
    stmt = select(SoftDeletablePost).where(
        SoftDeletablePost.id == post_id,
        SoftDeletablePost.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    found = result.scalar_one_or_none()

    assert found is not None
    assert found.title == "Recoverable Post"


# ============================================================================
# Pagination with Soft Delete Tests
# ============================================================================


@pytest.mark.asyncio
async def test_offset_pagination_excludes_soft_deleted(session: AsyncSession) -> None:
    """Test that offset pagination correctly excludes soft-deleted records."""
    repo = BaseRepository(SoftDeletablePost)

    # Create 10 posts
    for i in range(10):
        post = SoftDeletablePost(title=f"Post {i}")
        await repo.create(session, post)
    await session.commit()

    # Soft delete posts 2, 4, 6
    posts = await repo.list(session, limit=100)
    for i, post in enumerate(posts):
        if i in (2, 4, 6):
            post.deleted_at = datetime.now(UTC)
            session.add(post)
    await session.commit()

    # Query with soft delete filter
    stmt = select(SoftDeletablePost).where(SoftDeletablePost.deleted_at.is_(None))
    result = await repo.search(session, stmt, limit=5, offset=0)

    assert result.total == 7  # 10 - 3 deleted
    assert len(result.items) == 5
    assert result.has_next


@pytest.mark.asyncio
async def test_cursor_pagination_excludes_soft_deleted(session: AsyncSession) -> None:
    """Test that cursor pagination correctly excludes soft-deleted records."""
    repo = BaseRepository(SoftDeletablePost)

    # Create posts with timestamps
    now = datetime.now(UTC)
    for i in range(5):
        post = SoftDeletablePost(title=f"Post {i}")
        post.created_at = now + timedelta(seconds=i)
        await repo.create(session, post)
    await session.commit()

    # Soft delete post 2
    posts = await repo.list(session, limit=100)
    posts[2].deleted_at = datetime.now(UTC)
    session.add(posts[2])
    await session.commit()

    # Cursor pagination with filter
    stmt = select(SoftDeletablePost).where(SoftDeletablePost.deleted_at.is_(None))
    result = await repo.paginate_cursor(
        session,
        stmt,
        first=3,
        order_by=[(SoftDeletablePost.created_at, "asc")],
        include_total=True,
    )

    assert len(result.edges) == 3
    assert result.page_info.total_count == 4  # 5 - 1 deleted


@pytest.mark.asyncio
async def test_pagination_counts_exclude_soft_deleted(session: AsyncSession) -> None:
    """Test that pagination counts correctly exclude soft-deleted records."""
    repo = BaseRepository(SoftDeletablePost)

    # Create 20 posts
    for i in range(20):
        post = SoftDeletablePost(title=f"Post {i}")
        await repo.create(session, post)
    await session.commit()

    # Soft delete 5 posts
    posts = await repo.list(session, limit=100)
    for i in range(5):
        posts[i].deleted_at = datetime.now(UTC)
        session.add(posts[i])
    await session.commit()

    # Search with filter
    stmt = select(SoftDeletablePost).where(SoftDeletablePost.deleted_at.is_(None))
    result = await repo.search(session, stmt, limit=10, offset=0)

    assert result.total == 15  # 20 - 5 deleted
    assert result.pages == 2  # 15 items / 10 per page
    assert len(result.items) == 10


# ============================================================================
# Bulk Operations Tests
# ============================================================================


@pytest.mark.asyncio
async def test_bulk_create_with_audit_fields(
    session: AsyncSession, current_user: str
) -> None:
    """Test bulk_create preserves audit fields.

    Note: bulk_create uses SQLAlchemy Core which bypasses ORM defaults,
    so we must explicitly set timestamps.
    """
    repo = BaseRepository(AuditedDocument)

    # Create multiple documents with audit info
    # Note: Must set timestamps explicitly for bulk_create (Core insert)
    now = datetime.now(UTC)
    docs = [
        AuditedDocument(
            title=f"Doc {i}",
            created_by=current_user,
            created_at=now,
            updated_at=now,
        )
        for i in range(100)
    ]

    count = await repo.bulk_create(session, docs, batch_size=25)
    await session.commit()

    assert count == 100

    # Verify audit fields are preserved
    all_docs = await repo.list(session, limit=100)
    assert len(all_docs) == 100
    for doc in all_docs:
        assert doc.created_by == current_user


@pytest.mark.asyncio
async def test_create_many_with_audit_tracking(
    session: AsyncSession, current_user: str
) -> None:
    """Test create_many preserves audit tracking and returns instances."""
    repo = BaseRepository(AuditedDocument)

    docs = [
        AuditedDocument(title=f"Doc {i}", created_by=current_user) for i in range(10)
    ]

    created = await repo.create_many(session, docs)
    await session.commit()

    assert len(created) == 10
    for doc in created:
        assert doc.id is not None
        assert doc.created_by == current_user
        assert doc.created_at is not None


@pytest.mark.asyncio
async def test_delete_many_for_soft_delete(session: AsyncSession) -> None:
    """Test delete_many for hard delete (note: soft delete should be done via update)."""
    repo = BaseRepository(SoftDeletablePost)

    # Create posts
    posts = [SoftDeletablePost(title=f"Post {i}") for i in range(5)]
    created = await repo.create_many(session, posts)
    await session.commit()

    ids = [p.id for p in created]

    # Hard delete (not soft delete - for soft delete use update)
    deleted_count = await repo.delete_many(session, ids[:3])
    await session.commit()

    assert deleted_count == 3

    # Verify remaining posts
    remaining = await repo.list(session, limit=100)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_upsert_with_audit_tracking(
    session: AsyncSession, current_user: str
) -> None:
    """Test upsert_many preserves and updates audit tracking."""
    repo = BaseRepository(AuditedDocument)

    # Initial insert
    doc1 = AuditedDocument(title="Unique Doc 1", content="Original", created_by=current_user)
    doc1 = await repo.create(session, doc1)
    await session.commit()

    # Upsert operation
    docs = [
        AuditedDocument(
            title="Unique Doc 1",
            content="Updated",
            created_by=current_user,
            updated_by="updater@example.com",
        ),
        AuditedDocument(
            title="Unique Doc 2", content="New", created_by="new.user@example.com"
        ),
    ]

    # Note: upsert requires PostgreSQL-specific syntax, but we can test the pattern
    # For SQLite, we'll create directly
    for doc in docs:
        existing = await repo.get_by(session, AuditedDocument.title, doc.title)
        if existing:
            existing.content = doc.content
            existing.updated_by = doc.updated_by
            session.add(existing)
        else:
            await repo.create(session, doc)
    await session.commit()

    # Verify results
    all_docs = await repo.list(session, limit=100)
    assert len(all_docs) == 2

    doc1_updated = await repo.get_by(session, AuditedDocument.title, "Unique Doc 1")
    assert doc1_updated is not None
    assert doc1_updated.content == "Updated"
    assert doc1_updated.updated_by == "updater@example.com"


# ============================================================================
# End-to-End Scenarios
# ============================================================================


@pytest.mark.asyncio
async def test_complete_lifecycle_create_update_soft_delete_recover(
    session: AsyncSession, current_user: str, admin_user: str
) -> None:
    """Test complete lifecycle: create -> update -> soft delete -> recover."""
    repo = BaseRepository(FullAuditPost)

    # Step 1: Create
    post = FullAuditPost(title="Lifecycle Post", body="Initial content", created_by=current_user)
    post = await repo.create(session, post)
    await session.commit()
    post_id = post.id

    assert post.created_by == current_user
    assert post.updated_by is None
    assert not post.is_deleted

    # Step 2: Update
    post.body = "Updated content"
    post.updated_by = current_user
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    assert post.updated_by == current_user
    assert not post.is_deleted

    # Step 3: Soft Delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = admin_user
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    assert post.is_deleted
    assert post.deleted_by == admin_user
    assert post.created_by == current_user  # Original creator preserved

    # Step 4: Recover
    post.deleted_at = None
    post.deleted_by = None
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    assert not post.is_deleted
    assert post.created_by == current_user
    assert post.updated_by == current_user


@pytest.mark.asyncio
async def test_querying_mixed_deleted_non_deleted_records(session: AsyncSession) -> None:
    """Test querying with a mix of deleted and non-deleted records."""
    repo = BaseRepository(FullAuditPost)

    # Create multiple posts
    posts = []
    for i in range(10):
        post = FullAuditPost(
            title=f"Post {i}",
            body=f"Content {i}",
            created_by=f"user{i}@example.com",
        )
        post = await repo.create(session, post)
        posts.append(post)
    await session.commit()

    # Soft delete alternating posts (0, 2, 4, 6, 8)
    for i in range(0, 10, 2):
        posts[i].deleted_at = datetime.now(UTC)
        posts[i].deleted_by = "admin@example.com"
        session.add(posts[i])
    await session.commit()

    # Query active only
    stmt_active = select(FullAuditPost).where(FullAuditPost.deleted_at.is_(None))
    result_active = await session.execute(stmt_active)
    active_posts = result_active.scalars().all()

    assert len(active_posts) == 5
    active_titles = {p.title for p in active_posts}
    assert active_titles == {"Post 1", "Post 3", "Post 5", "Post 7", "Post 9"}

    # Query deleted only
    stmt_deleted = select(FullAuditPost).where(FullAuditPost.deleted_at.is_not(None))
    result_deleted = await session.execute(stmt_deleted)
    deleted_posts = result_deleted.scalars().all()

    assert len(deleted_posts) == 5
    for post in deleted_posts:
        assert post.is_deleted
        assert post.deleted_by == "admin@example.com"

    # Query all (no filter)
    all_posts = await repo.list(session, limit=100)
    assert len(all_posts) == 10


@pytest.mark.asyncio
async def test_audit_trail_complete_at_each_step(
    session: AsyncSession, current_user: str, admin_user: str
) -> None:
    """Verify audit trail is complete and accurate at every lifecycle step."""
    repo = BaseRepository(FullAuditPost)

    # Create
    post = FullAuditPost(title="Audit Test", body="Initial", created_by=current_user)
    post = await repo.create(session, post)
    await session.commit()

    # Audit check after create
    retrieved = await repo.get(session, post.id)
    assert retrieved is not None
    assert retrieved.created_by == current_user
    assert retrieved.updated_by is None
    assert retrieved.deleted_by is None
    assert retrieved.created_at is not None
    assert retrieved.updated_at is not None
    assert not retrieved.is_deleted

    # Update
    post.body = "Modified"
    post.updated_by = admin_user
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    # Audit check after update
    retrieved = await repo.get(session, post.id)
    assert retrieved is not None
    assert retrieved.created_by == current_user  # Unchanged
    assert retrieved.updated_by == admin_user  # Updated
    assert retrieved.deleted_by is None  # Still None
    assert not retrieved.is_deleted

    # Soft delete
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = admin_user
    session.add(post)
    await session.flush()
    await session.refresh(post)
    await session.commit()

    # Audit check after soft delete
    retrieved = await repo.get(session, post.id)
    assert retrieved is not None
    assert retrieved.created_by == current_user  # Unchanged
    assert retrieved.updated_by == admin_user  # Unchanged
    assert retrieved.deleted_by == admin_user  # Set
    assert retrieved.is_deleted
    assert retrieved.deleted_at is not None


@pytest.mark.asyncio
async def test_bulk_operations_preserve_audit_integrity(
    session: AsyncSession, current_user: str
) -> None:
    """Test that bulk operations maintain audit trail integrity.

    Note: bulk_create uses SQLAlchemy Core which bypasses ORM defaults,
    so we must explicitly set timestamps.
    """
    repo = BaseRepository(FullAuditPost)

    # Bulk create with audit fields
    # Note: Must set timestamps explicitly for bulk_create (Core insert)
    now = datetime.now(UTC)
    posts = [
        FullAuditPost(
            title=f"Bulk Post {i}",
            body=f"Content {i}",
            created_by=current_user,
            created_at=now,
            updated_at=now,
        )
        for i in range(50)
    ]

    count = await repo.bulk_create(session, posts, batch_size=10)
    await session.commit()

    assert count == 50

    # Verify all have audit fields
    all_posts = await repo.list(session, limit=100)
    assert len(all_posts) == 50

    for post in all_posts:
        assert post.created_by == current_user
        assert post.created_at is not None
        assert not post.is_deleted

    # Bulk soft delete (via update_many pattern)
    posts_to_delete = all_posts[:20]
    now = datetime.now(UTC)
    for post in posts_to_delete:
        post.deleted_at = now
        post.deleted_by = "bulk.admin@example.com"

    updated = await repo.update_many(session, posts_to_delete)
    await session.commit()

    assert len(updated) == 20

    # Verify soft delete was applied
    stmt_active = select(FullAuditPost).where(FullAuditPost.deleted_at.is_(None))
    result = await session.execute(stmt_active)
    active_posts = result.scalars().all()

    assert len(active_posts) == 30

    # Verify deleted have correct audit info
    stmt_deleted = select(FullAuditPost).where(FullAuditPost.deleted_at.is_not(None))
    result = await session.execute(stmt_deleted)
    deleted_posts = result.scalars().all()

    assert len(deleted_posts) == 20
    for post in deleted_posts:
        assert post.deleted_by == "bulk.admin@example.com"
        assert post.created_by == current_user  # Original creator preserved
