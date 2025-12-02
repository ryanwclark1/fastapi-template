"""Feature flag repository for database operations.

Provides data access layer for feature flags and overrides,
separating persistence concerns from business logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select

from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.infra.logging import get_lazy_logger

from .models import FeatureFlag, FlagOverride, FlagStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

_lazy = get_lazy_logger(__name__)


class FeatureFlagRepository(BaseRepository[FeatureFlag]):
    """Repository for FeatureFlag database operations.

    Provides methods for:
    - CRUD operations on feature flags
    - Filtered listing with pagination
    - Key-based lookups

    Example:
        repo = FeatureFlagRepository()
        flag = await repo.get_by_key(session, "my_feature")
        flags = await repo.list_with_filters(session, status=FlagStatus.ENABLED)
    """

    def __init__(self) -> None:
        """Initialize feature flag repository."""
        super().__init__(FeatureFlag)

    async def get_by_key(
        self,
        session: AsyncSession,
        key: str,
    ) -> FeatureFlag | None:
        """Get a feature flag by its unique key.

        Args:
            session: Database session.
            key: Flag key.

        Returns:
            Feature flag if found, None otherwise.
        """
        stmt = select(FeatureFlag).where(FeatureFlag.key == key)
        result = await session.execute(stmt)
        flag = result.scalar_one_or_none()

        _lazy.debug(lambda: f"get_by_key: {key} -> {'found' if flag else 'not found'}")
        return flag

    async def list_with_filters(
        self,
        session: AsyncSession,
        *,
        status: FlagStatus | None = None,
        enabled: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult[FeatureFlag]:
        """List feature flags with optional filters.

        Args:
            session: Database session.
            status: Filter by status.
            enabled: Filter by enabled state.
            limit: Maximum flags to return.
            offset: Number to skip.

        Returns:
            SearchResult with paginated flags and total count.
        """
        stmt = select(FeatureFlag)

        if status:
            stmt = stmt.where(FeatureFlag.status == status.value)
        if enabled is not None:
            stmt = stmt.where(FeatureFlag.enabled == enabled)

        stmt = stmt.order_by(FeatureFlag.key)

        return await self.search(session, stmt, limit=limit, offset=offset)

    async def get_by_keys(
        self,
        session: AsyncSession,
        keys: list[str],
    ) -> Sequence[FeatureFlag]:
        """Get multiple flags by their keys.

        Args:
            session: Database session.
            keys: List of flag keys.

        Returns:
            Sequence of found flags.
        """
        if not keys:
            return []

        stmt = select(FeatureFlag).where(FeatureFlag.key.in_(keys))
        result = await session.execute(stmt)
        flags = result.scalars().all()

        _lazy.debug(lambda: f"get_by_keys: {len(keys)} requested -> {len(flags)} found")
        return flags

    async def get_all(
        self,
        session: AsyncSession,
    ) -> Sequence[FeatureFlag]:
        """Get all feature flags.

        Args:
            session: Database session.

        Returns:
            All feature flags.
        """
        stmt = select(FeatureFlag)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def delete_by_key(
        self,
        session: AsyncSession,
        key: str,
    ) -> bool:
        """Delete a feature flag by key.

        Args:
            session: Database session.
            key: Flag key.

        Returns:
            True if deleted, False if not found.
        """
        flag = await self.get_by_key(session, key)
        if not flag:
            return False

        await session.delete(flag)
        await session.flush()

        self._logger.info("Feature flag deleted", extra={"key": key})
        return True


class FlagOverrideRepository(BaseRepository[FlagOverride]):
    """Repository for FlagOverride database operations.

    Provides methods for:
    - CRUD operations on flag overrides
    - Querying overrides by user/tenant context
    - Bulk deletion by flag key

    Example:
        repo = FlagOverrideRepository()
        overrides = await repo.get_by_context(session, user_id="user-123")
    """

    def __init__(self) -> None:
        """Initialize flag override repository."""
        super().__init__(FlagOverride)

    async def get_by_entity(
        self,
        session: AsyncSession,
        flag_key: str,
        entity_type: str,
        entity_id: str,
    ) -> FlagOverride | None:
        """Get a specific override by entity.

        Args:
            session: Database session.
            flag_key: Flag key.
            entity_type: Entity type (user/tenant).
            entity_id: Entity identifier.

        Returns:
            Override if found, None otherwise.
        """
        stmt = select(FlagOverride).where(
            FlagOverride.flag_key == flag_key,
            FlagOverride.entity_type == entity_type,
            FlagOverride.entity_id == entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        session: AsyncSession,
        override: FlagOverride,
    ) -> FlagOverride:
        """Create or update an override.

        If an override with the same flag_key/entity_type/entity_id exists,
        it will be updated. Otherwise, a new one is created.

        Args:
            session: Database session.
            override: Override to create or update.

        Returns:
            Created or updated override.
        """
        existing = await self.get_by_entity(
            session,
            override.flag_key,
            override.entity_type,
            override.entity_id,
        )

        if existing:
            existing.enabled = override.enabled
            existing.reason = override.reason
            await session.flush()
            await session.refresh(existing)
            _lazy.debug(lambda: f"upsert: updated override for {override.flag_key}")
            return existing

        session.add(override)
        await session.flush()
        await session.refresh(override)
        _lazy.debug(lambda: f"upsert: created override for {override.flag_key}")
        return override

    async def list_with_filters(
        self,
        session: AsyncSession,
        *,
        flag_key: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> Sequence[FlagOverride]:
        """List overrides with optional filters.

        Args:
            session: Database session.
            flag_key: Filter by flag key.
            entity_type: Filter by entity type.
            entity_id: Filter by entity ID.

        Returns:
            List of matching overrides.
        """
        stmt = select(FlagOverride)

        if flag_key:
            stmt = stmt.where(FlagOverride.flag_key == flag_key)
        if entity_type:
            stmt = stmt.where(FlagOverride.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(FlagOverride.entity_id == entity_id)

        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_context(
        self,
        session: AsyncSession,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, bool]:
        """Get overrides applicable to a user/tenant context.

        Returns a mapping of flag_key -> enabled for all applicable overrides.
        User-level overrides take precedence over tenant-level ones.

        Args:
            session: Database session.
            user_id: User identifier.
            tenant_id: Tenant identifier.

        Returns:
            Dictionary mapping flag keys to their override values.
        """
        if not user_id and not tenant_id:
            return {}

        conditions = []
        if user_id:
            conditions.append(
                (FlagOverride.entity_type == "user") & (FlagOverride.entity_id == user_id)
            )
        if tenant_id:
            conditions.append(
                (FlagOverride.entity_type == "tenant") & (FlagOverride.entity_id == tenant_id)
            )

        stmt = select(FlagOverride).where(or_(*conditions))
        result = await session.execute(stmt)

        # Build override dict - user overrides take precedence
        overrides: dict[str, bool] = {}
        tenant_overrides: dict[str, bool] = {}

        for override in result.scalars():
            if override.entity_type == "user":
                overrides[override.flag_key] = override.enabled
            else:
                tenant_overrides[override.flag_key] = override.enabled

        # Merge tenant overrides (only if not already set by user)
        for key, enabled in tenant_overrides.items():
            if key not in overrides:
                overrides[key] = enabled

        _lazy.debug(lambda: f"get_by_context: found {len(overrides)} overrides")
        return overrides

    async def delete_by_entity(
        self,
        session: AsyncSession,
        flag_key: str,
        entity_type: str,
        entity_id: str,
    ) -> bool:
        """Delete a specific override.

        Args:
            session: Database session.
            flag_key: Flag key.
            entity_type: Entity type.
            entity_id: Entity identifier.

        Returns:
            True if deleted, False if not found.
        """
        stmt = delete(FlagOverride).where(
            FlagOverride.flag_key == flag_key,
            FlagOverride.entity_type == entity_type,
            FlagOverride.entity_id == entity_id,
        )
        result = await session.execute(stmt)
        await session.flush()

        deleted = (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        if deleted:
            _lazy.debug(
                lambda: f"delete_by_entity: removed override for {flag_key}/{entity_type}/{entity_id}"
            )
        return deleted

    async def delete_by_flag(
        self,
        session: AsyncSession,
        flag_key: str,
    ) -> int:
        """Delete all overrides for a flag.

        Args:
            session: Database session.
            flag_key: Flag key.

        Returns:
            Number of deleted overrides.
        """
        stmt = delete(FlagOverride).where(FlagOverride.flag_key == flag_key)
        result = await session.execute(stmt)
        await session.flush()

        deleted_count: int = result.rowcount or 0  # type: ignore[attr-defined]
        if deleted_count > 0:
            self._logger.info(
                "Flag overrides deleted",
                extra={"flag_key": flag_key, "count": deleted_count},
            )
        return deleted_count


# Global singleton instances
_flag_repository: FeatureFlagRepository | None = None
_override_repository: FlagOverrideRepository | None = None


def get_feature_flag_repository() -> FeatureFlagRepository:
    """Get the global FeatureFlagRepository instance.

    Returns:
        Singleton FeatureFlagRepository instance.
    """
    global _flag_repository
    if _flag_repository is None:
        _flag_repository = FeatureFlagRepository()
    return _flag_repository


def get_flag_override_repository() -> FlagOverrideRepository:
    """Get the global FlagOverrideRepository instance.

    Returns:
        Singleton FlagOverrideRepository instance.
    """
    global _override_repository
    if _override_repository is None:
        _override_repository = FlagOverrideRepository()
    return _override_repository


__all__ = [
    "FeatureFlagRepository",
    "FlagOverrideRepository",
    "get_feature_flag_repository",
    "get_flag_override_repository",
]
