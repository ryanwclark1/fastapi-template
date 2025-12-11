"""DataLoaders for batch-loading feature flags.

Prevents N+1 queries when resolving feature flag references.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.featureflags.models import FeatureFlag

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FeatureFlagDataLoader:
    """DataLoader for batch-loading feature flags by ID.

    Prevents N+1 queries when resolving feature flag references.

    Usage:
        loader = FeatureFlagDataLoader(session)
        flag = await loader.load(uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, FeatureFlag | None] = DataLoader(
            load_fn=self._batch_load_flags,
        )

    async def _batch_load_flags(
        self,
        ids: list[UUID],
    ) -> list[FeatureFlag | None]:
        """Batch load feature flags by IDs.

        Args:
            ids: List of feature flag UUIDs to load

        Returns:
            List of FeatureFlag objects (or None) in same order as ids
        """
        if not ids:
            return []

        stmt = select(FeatureFlag).where(FeatureFlag.id.in_(ids))
        result = await self._session.execute(stmt)
        flags = {f.id: f for f in result.scalars().all()}

        return [flags.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> FeatureFlag | None:
        """Load a single feature flag by ID.

        Args:
            id_: Feature flag UUID

        Returns:
            FeatureFlag if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[FeatureFlag | None]:
        """Load multiple feature flags by IDs.

        Args:
            ids: List of feature flag UUIDs

        Returns:
            List of FeatureFlag objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class FeatureFlagByKeyDataLoader:
    """DataLoader for batch-loading feature flags by key.

    Optimized for flag evaluation by key lookup.
    Maps flag key -> FeatureFlag.

    Usage:
        loader = FeatureFlagByKeyDataLoader(session)
        flag = await loader.load("new_dashboard")
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[str, FeatureFlag | None] = DataLoader(
            load_fn=self._batch_load_flags_by_key,
        )

    async def _batch_load_flags_by_key(
        self,
        keys: list[str],
    ) -> list[FeatureFlag | None]:
        """Batch load feature flags by keys.

        Args:
            keys: List of feature flag keys to load

        Returns:
            List of FeatureFlag objects (or None) in same order as keys
        """
        if not keys:
            return []

        stmt = select(FeatureFlag).where(FeatureFlag.key.in_(keys))
        result = await self._session.execute(stmt)
        flags = {f.key: f for f in result.scalars().all()}

        return [flags.get(key) for key in keys]

    async def load(self, key: str) -> FeatureFlag | None:
        """Load a single feature flag by key.

        Args:
            key: Feature flag key (e.g., "new_dashboard")

        Returns:
            FeatureFlag if found, None otherwise
        """
        return await self._loader.load(key)

    async def load_many(self, keys: list[str]) -> list[FeatureFlag | None]:
        """Load multiple feature flags by keys.

        Args:
            keys: List of feature flag keys

        Returns:
            List of FeatureFlag objects (or None) in same order as keys
        """
        return await self._loader.load_many(keys)


__all__ = ["FeatureFlagByKeyDataLoader", "FeatureFlagDataLoader"]
