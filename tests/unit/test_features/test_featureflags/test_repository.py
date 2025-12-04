"""Unit tests for FeatureFlagRepository and FlagOverrideRepository."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.features.featureflags.models import FeatureFlag, FlagOverride, FlagStatus
from example_service.features.featureflags.repository import (
    FeatureFlagRepository,
    FlagOverrideRepository,
    get_feature_flag_repository,
    get_flag_override_repository,
)


@pytest.fixture
def flag_repository() -> FeatureFlagRepository:
    """Create FeatureFlagRepository instance."""
    return FeatureFlagRepository()


@pytest.fixture
def override_repository() -> FlagOverrideRepository:
    """Create FlagOverrideRepository instance."""
    return FlagOverrideRepository()


@pytest.mark.asyncio
async def test_flag_repository_initialization(flag_repository: FeatureFlagRepository) -> None:
    """Test that repository initializes correctly."""
    assert flag_repository is not None
    assert flag_repository.model == FeatureFlag


@pytest.mark.asyncio
async def test_get_feature_flag_repository_returns_singleton() -> None:
    """Test that get_feature_flag_repository returns singleton instance."""
    repo1 = get_feature_flag_repository()
    repo2 = get_feature_flag_repository()

    assert repo1 is repo2
    assert isinstance(repo1, FeatureFlagRepository)


@pytest.mark.asyncio
async def test_get_flag_override_repository_returns_singleton() -> None:
    """Test that get_flag_override_repository returns singleton instance."""
    repo1 = get_flag_override_repository()
    repo2 = get_flag_override_repository()

    assert repo1 is repo2
    assert isinstance(repo1, FlagOverrideRepository)


@pytest.mark.asyncio
async def test_get_by_key_found(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test getting flag by key when it exists."""
    flag = FeatureFlag(
        key="test_flag",
        name="Test Flag",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag = await flag_repository.create(db_session, flag)
    await db_session.commit()

    result = await flag_repository.get_by_key(db_session, "test_flag")

    assert result is not None
    assert result.key == "test_flag"
    assert result.id == flag.id


@pytest.mark.asyncio
async def test_get_by_key_not_found(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test getting flag by key when it doesn't exist."""
    result = await flag_repository.get_by_key(db_session, "nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_list_with_filters_by_status(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test listing flags filtered by status."""
    flag1 = FeatureFlag(
        key="enabled_flag",
        name="Enabled Flag",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag2 = FeatureFlag(
        key="disabled_flag",
        name="Disabled Flag",
        status=FlagStatus.DISABLED.value,
        enabled=False,
    )
    await flag_repository.create(db_session, flag1)
    await flag_repository.create(db_session, flag2)
    await db_session.commit()

    result = await flag_repository.list_with_filters(
        db_session, status=FlagStatus.ENABLED, limit=100
    )

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].key == "enabled_flag"


@pytest.mark.asyncio
async def test_list_with_filters_by_enabled(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test listing flags filtered by enabled state."""
    flag1 = FeatureFlag(
        key="flag1",
        name="Flag 1",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag2 = FeatureFlag(
        key="flag2",
        name="Flag 2",
        status=FlagStatus.ENABLED.value,
        enabled=False,
    )
    await flag_repository.create(db_session, flag1)
    await flag_repository.create(db_session, flag2)
    await db_session.commit()

    result = await flag_repository.list_with_filters(db_session, enabled=True, limit=100)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].key == "flag1"


@pytest.mark.asyncio
async def test_list_with_filters_pagination(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test pagination in list_with_filters."""
    for i in range(10):
        flag = FeatureFlag(
            key=f"flag_{i}",
            name=f"Flag {i}",
            status=FlagStatus.ENABLED.value,
            enabled=True,
        )
        await flag_repository.create(db_session, flag)
    await db_session.commit()

    result = await flag_repository.list_with_filters(db_session, limit=5, offset=0)

    assert result.total == 10
    assert len(result.items) == 5

    result2 = await flag_repository.list_with_filters(db_session, limit=5, offset=5)

    assert result2.total == 10
    assert len(result2.items) == 5
    assert result.items[0].id != result2.items[0].id


@pytest.mark.asyncio
async def test_get_by_keys(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test getting multiple flags by keys."""
    flag1 = FeatureFlag(
        key="flag1",
        name="Flag 1",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag2 = FeatureFlag(
        key="flag2",
        name="Flag 2",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag3 = FeatureFlag(
        key="flag3",
        name="Flag 3",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    await flag_repository.create(db_session, flag1)
    await flag_repository.create(db_session, flag2)
    await flag_repository.create(db_session, flag3)
    await db_session.commit()

    result = await flag_repository.get_by_keys(db_session, ["flag1", "flag2", "nonexistent"])

    assert len(result) == 2
    keys = {f.key for f in result}
    assert keys == {"flag1", "flag2"}


@pytest.mark.asyncio
async def test_get_by_keys_empty_list(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test getting flags with empty key list."""
    result = await flag_repository.get_by_keys(db_session, [])

    assert len(result) == 0


@pytest.mark.asyncio
async def test_get_all(db_session: AsyncSession, flag_repository: FeatureFlagRepository) -> None:
    """Test getting all flags."""
    for i in range(5):
        flag = FeatureFlag(
            key=f"flag_{i}",
            name=f"Flag {i}",
            status=FlagStatus.ENABLED.value,
            enabled=True,
        )
        await flag_repository.create(db_session, flag)
    await db_session.commit()

    result = await flag_repository.get_all(db_session)

    assert len(result) == 5


@pytest.mark.asyncio
async def test_delete_by_key_found(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test deleting flag by key when it exists."""
    flag = FeatureFlag(
        key="to_delete",
        name="To Delete",
        status=FlagStatus.ENABLED.value,
        enabled=True,
    )
    flag = await flag_repository.create(db_session, flag)
    await db_session.commit()

    deleted = await flag_repository.delete_by_key(db_session, "to_delete")
    await db_session.commit()

    assert deleted is True
    assert await flag_repository.get_by_key(db_session, "to_delete") is None


@pytest.mark.asyncio
async def test_delete_by_key_not_found(
    db_session: AsyncSession, flag_repository: FeatureFlagRepository
) -> None:
    """Test deleting flag by key when it doesn't exist."""
    deleted = await flag_repository.delete_by_key(db_session, "nonexistent")

    assert deleted is False


@pytest.mark.asyncio
async def test_override_repository_initialization(
    override_repository: FlagOverrideRepository,
) -> None:
    """Test that override repository initializes correctly."""
    assert override_repository is not None
    assert override_repository.model == FlagOverride


@pytest.mark.asyncio
async def test_get_by_entity_found(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting override by entity when it exists."""
    override = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
    )
    override = await override_repository.create(db_session, override)
    await db_session.commit()

    result = await override_repository.get_by_entity(db_session, "test_flag", "user", "user-123")

    assert result is not None
    assert result.flag_key == "test_flag"
    assert result.entity_type == "user"
    assert result.entity_id == "user-123"
    assert result.id == override.id


@pytest.mark.asyncio
async def test_get_by_entity_not_found(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting override by entity when it doesn't exist."""
    result = await override_repository.get_by_entity(db_session, "test_flag", "user", "user-123")

    assert result is None


@pytest.mark.asyncio
async def test_upsert_creates_new(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test upsert creates new override when it doesn't exist."""
    override = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
        reason="Test reason",
    )

    result = await override_repository.upsert(db_session, override)
    await db_session.commit()

    assert result.id is not None
    assert result.flag_key == "test_flag"
    assert result.enabled is True
    assert result.reason == "Test reason"


@pytest.mark.asyncio
async def test_upsert_updates_existing(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test upsert updates existing override."""
    override1 = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
        reason="Original reason",
    )
    override1 = await override_repository.create(db_session, override1)
    await db_session.commit()

    override2 = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=False,
        reason="Updated reason",
    )

    result = await override_repository.upsert(db_session, override2)
    await db_session.commit()

    assert result.id == override1.id
    assert result.enabled is False
    assert result.reason == "Updated reason"


@pytest.mark.asyncio
async def test_list_with_filters_by_flag_key(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test listing overrides filtered by flag key."""
    override1 = FlagOverride(
        flag_key="flag1",
        entity_type="user",
        entity_id="user-1",
        enabled=True,
    )
    override2 = FlagOverride(
        flag_key="flag2",
        entity_type="user",
        entity_id="user-2",
        enabled=True,
    )
    await override_repository.create(db_session, override1)
    await override_repository.create(db_session, override2)
    await db_session.commit()

    result = await override_repository.list_with_filters(db_session, flag_key="flag1")

    assert len(result) == 1
    assert result[0].flag_key == "flag1"


@pytest.mark.asyncio
async def test_list_with_filters_by_entity_type(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test listing overrides filtered by entity type."""
    override1 = FlagOverride(
        flag_key="flag1",
        entity_type="user",
        entity_id="user-1",
        enabled=True,
    )
    override2 = FlagOverride(
        flag_key="flag1",
        entity_type="tenant",
        entity_id="tenant-1",
        enabled=True,
    )
    await override_repository.create(db_session, override1)
    await override_repository.create(db_session, override2)
    await db_session.commit()

    result = await override_repository.list_with_filters(db_session, entity_type="user")

    assert len(result) == 1
    assert result[0].entity_type == "user"


@pytest.mark.asyncio
async def test_list_with_filters_by_entity_id(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test listing overrides filtered by entity ID."""
    override1 = FlagOverride(
        flag_key="flag1",
        entity_type="user",
        entity_id="user-1",
        enabled=True,
    )
    override2 = FlagOverride(
        flag_key="flag1",
        entity_type="user",
        entity_id="user-2",
        enabled=True,
    )
    await override_repository.create(db_session, override1)
    await override_repository.create(db_session, override2)
    await db_session.commit()

    result = await override_repository.list_with_filters(db_session, entity_id="user-1")

    assert len(result) == 1
    assert result[0].entity_id == "user-1"


@pytest.mark.asyncio
async def test_get_by_context_user_only(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting overrides by context with user only."""
    override = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
    )
    await override_repository.create(db_session, override)
    await db_session.commit()

    result = await override_repository.get_by_context(db_session, user_id="user-123")

    assert result == {"test_flag": True}


@pytest.mark.asyncio
async def test_get_by_context_tenant_only(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting overrides by context with tenant only."""
    override = FlagOverride(
        flag_key="test_flag",
        entity_type="tenant",
        entity_id="tenant-123",
        enabled=False,
    )
    await override_repository.create(db_session, override)
    await db_session.commit()

    result = await override_repository.get_by_context(db_session, tenant_id="tenant-123")

    assert result == {"test_flag": False}


@pytest.mark.asyncio
async def test_get_by_context_user_precedence(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test that user overrides take precedence over tenant overrides."""
    user_override = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
    )
    tenant_override = FlagOverride(
        flag_key="test_flag",
        entity_type="tenant",
        entity_id="tenant-123",
        enabled=False,
    )
    await override_repository.create(db_session, user_override)
    await override_repository.create(db_session, tenant_override)
    await db_session.commit()

    result = await override_repository.get_by_context(
        db_session, user_id="user-123", tenant_id="tenant-123"
    )

    assert result == {"test_flag": True}  # User override takes precedence


@pytest.mark.asyncio
async def test_get_by_context_no_context(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting overrides with no context."""
    result = await override_repository.get_by_context(db_session)

    assert result == {}


@pytest.mark.asyncio
async def test_get_by_context_multiple_flags(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test getting multiple flag overrides by context."""
    override1 = FlagOverride(
        flag_key="flag1",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
    )
    override2 = FlagOverride(
        flag_key="flag2",
        entity_type="user",
        entity_id="user-123",
        enabled=False,
    )
    await override_repository.create(db_session, override1)
    await override_repository.create(db_session, override2)
    await db_session.commit()

    result = await override_repository.get_by_context(db_session, user_id="user-123")

    assert result == {"flag1": True, "flag2": False}


@pytest.mark.asyncio
async def test_delete_by_entity_found(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test deleting override by entity when it exists."""
    override = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-123",
        enabled=True,
    )
    override = await override_repository.create(db_session, override)
    await db_session.commit()

    deleted = await override_repository.delete_by_entity(
        db_session, "test_flag", "user", "user-123"
    )
    await db_session.commit()

    assert deleted is True
    assert (
        await override_repository.get_by_entity(db_session, "test_flag", "user", "user-123") is None
    )


@pytest.mark.asyncio
async def test_delete_by_entity_not_found(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test deleting override by entity when it doesn't exist."""
    deleted = await override_repository.delete_by_entity(
        db_session, "test_flag", "user", "user-123"
    )

    assert deleted is False


@pytest.mark.asyncio
async def test_delete_by_flag(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test deleting all overrides for a flag."""
    override1 = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-1",
        enabled=True,
    )
    override2 = FlagOverride(
        flag_key="test_flag",
        entity_type="user",
        entity_id="user-2",
        enabled=False,
    )
    override3 = FlagOverride(
        flag_key="other_flag",
        entity_type="user",
        entity_id="user-1",
        enabled=True,
    )
    await override_repository.create(db_session, override1)
    await override_repository.create(db_session, override2)
    await override_repository.create(db_session, override3)
    await db_session.commit()

    deleted_count = await override_repository.delete_by_flag(db_session, "test_flag")
    await db_session.commit()

    assert deleted_count == 2
    assert (
        await override_repository.get_by_entity(db_session, "test_flag", "user", "user-1") is None
    )
    assert (
        await override_repository.get_by_entity(db_session, "test_flag", "user", "user-2") is None
    )
    # Other flag should still exist
    assert (
        await override_repository.get_by_entity(db_session, "other_flag", "user", "user-1")
        is not None
    )


@pytest.mark.asyncio
async def test_delete_by_flag_no_matches(
    db_session: AsyncSession, override_repository: FlagOverrideRepository
) -> None:
    """Test deleting overrides for a flag that has none."""
    deleted_count = await override_repository.delete_by_flag(db_session, "nonexistent")

    assert deleted_count == 0
