"""DataLoader container and factory.

DataLoaders batch and cache database lookups within a single request,
preventing N+1 query problems common in GraphQL resolvers.

Each GraphQL request gets its own DataLoader instance to ensure proper
batching boundaries and cache isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from example_service.features.graphql.dataloaders.reminders import ReminderDataLoader

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class DataLoaders:
    """Container for all DataLoader instances.

    One instance created per GraphQL request.
    Provides typed access to loaders.

    Usage in resolver:
        ctx = info.context
        reminder = await ctx.loaders.reminders.load(reminder_id)
    """

    reminders: ReminderDataLoader


def create_dataloaders(session: AsyncSession) -> DataLoaders:
    """Factory for creating request-scoped DataLoaders.

    Args:
        session: Database session for the current request

    Returns:
        DataLoaders container with all loaders initialized
    """
    return DataLoaders(
        reminders=ReminderDataLoader(session),
    )


__all__ = ["DataLoaders", "create_dataloaders", "ReminderDataLoader"]
