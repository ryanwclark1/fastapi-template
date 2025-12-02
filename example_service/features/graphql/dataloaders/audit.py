"""DataLoader for batch-loading audit logs.

Prevents N+1 queries when resolving audit log references.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.audit.models import AuditLog

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class AuditLogDataLoader:
    """DataLoader for batch-loading audit logs by ID.

    Prevents N+1 queries when resolving audit log references.
    Audit logs use UUIDv7 for time-sortable IDs.

    Usage:
        loader = AuditLogDataLoader(session)
        audit_log = await loader.load(uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, AuditLog | None] = DataLoader(
            load_fn=self._batch_load_audit_logs
        )

    async def _batch_load_audit_logs(
        self,
        ids: list[UUID],
    ) -> list[AuditLog | None]:
        """Batch load audit logs by IDs.

        Args:
            ids: List of audit log UUIDs to load

        Returns:
            List of AuditLog objects (or None) in same order as ids
        """
        if not ids:
            return []

        stmt = select(AuditLog).where(AuditLog.id.in_(ids))
        result = await self._session.execute(stmt)
        audit_logs = {log.id: log for log in result.scalars().all()}

        return [audit_logs.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> AuditLog | None:
        """Load a single audit log by ID.

        Args:
            id_: Audit log UUID

        Returns:
            AuditLog if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[AuditLog | None]:
        """Load multiple audit logs by IDs.

        Args:
            ids: List of audit log UUIDs

        Returns:
            List of AuditLog objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class AuditLogsByEntityDataLoader:
    """DataLoader for batch-loading audit logs by entity.

    Solves N+1 problem when loading audit history for multiple entities.
    Maps (entity_type, entity_id) -> list of audit logs.

    Usage:
        loader = AuditLogsByEntityDataLoader(session)
        audit_logs = await loader.load(("reminder", uuid))  # Returns list[AuditLog]
    """

    def __init__(self, session: AsyncSession, limit: int = 50) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
            limit: Maximum number of logs to return per entity (default: 50)
        """
        self._session = session
        self._limit = limit
        self._loader: DataLoader[tuple[str, str], list[AuditLog]] = DataLoader(
            load_fn=self._batch_load_logs_by_entity
        )

    async def _batch_load_logs_by_entity(
        self,
        entity_keys: list[tuple[str, str]],
    ) -> list[list[AuditLog]]:
        """Batch load audit logs for multiple entities.

        Returns most recent logs up to limit per entity.

        Args:
            entity_keys: List of (entity_type, entity_id) tuples

        Returns:
            List of audit log lists, one per entity_key (empty list if none)
        """
        if not entity_keys:
            return []

        # Build OR conditions for all entity pairs
        from sqlalchemy import and_, or_

        conditions = [
            and_(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            for entity_type, entity_id in entity_keys
        ]

        # Single query for all audit logs
        stmt = select(AuditLog).where(or_(*conditions)).order_by(AuditLog.timestamp.desc())
        result = await self._session.execute(stmt)
        all_logs = result.scalars().all()

        # Group by (entity_type, entity_id), limit per entity
        logs_by_entity: dict[tuple[str, str], list[AuditLog]] = {key: [] for key in entity_keys}
        for log in all_logs:
            key = (log.entity_type, log.entity_id)
            entity_logs = logs_by_entity.setdefault(key, [])
            if len(entity_logs) < self._limit:
                entity_logs.append(log)

        # Return in same order as requested
        return [logs_by_entity.get(key, []) for key in entity_keys]

    async def load(self, entity_key: tuple[str, str]) -> list[AuditLog]:
        """Load audit logs for a single entity.

        Args:
            entity_key: Tuple of (entity_type, entity_id)

        Returns:
            List of audit logs for the entity (empty list if none, max limit)
        """
        return await self._loader.load(entity_key)

    async def load_many(self, entity_keys: list[tuple[str, str]]) -> list[list[AuditLog]]:
        """Load audit logs for multiple entities.

        Args:
            entity_keys: List of (entity_type, entity_id) tuples

        Returns:
            List of audit log lists, one per entity_key
        """
        return await self._loader.load_many(entity_keys)


__all__ = ["AuditLogDataLoader", "AuditLogsByEntityDataLoader"]
