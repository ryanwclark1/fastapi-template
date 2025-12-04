"""Repository for the files feature.

Supports optional multi-tenancy: when tenant_id is provided, all queries
are automatically scoped to that tenant. When tenant_id is None, operates
in single-tenant mode with no tenant filtering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from example_service.core.database import SearchFilter
from example_service.core.database.repository import SearchResult, TenantAwareRepository
from example_service.features.files.models import File, FileStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FileRepository(TenantAwareRepository[File]):
    """Repository for File model with optional multi-tenancy support.

    Inherits from TenantAwareRepository (which extends BaseRepository):
        - get(session, id) -> File | None
        - get_or_raise(session, id) -> File
        - get_by(session, attr, value) -> File | None
        - list(session, limit, offset) -> Sequence[File]
        - search(session, statement, limit, offset) -> SearchResult[File]
        - create(session, instance) -> File
        - create_many(session, instances) -> Sequence[File]
        - delete(session, instance) -> None

    Tenant-aware methods (add tenant_id=None for optional filtering):
        - get_for_tenant(session, id, tenant_id) -> File | None
        - list_for_tenant(session, tenant_id, limit, offset) -> Sequence[File]
        - search_for_tenant(session, statement, tenant_id) -> SearchResult[File]

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with File model."""
        super().__init__(File)

    async def get_by_storage_key(
        self,
        session: AsyncSession,
        storage_key: str,
        *,
        tenant_id: str | None = None,
    ) -> File | None:
        """Get file by its storage key.

        Args:
            session: Database session
            storage_key: S3 storage key
            tenant_id: Optional tenant ID for multi-tenant filtering.
                      If None, no tenant filtering is applied (single-tenant mode).

        Returns:
            File if found, None otherwise
        """
        stmt = select(File).where(File.storage_key == storage_key)
        stmt = self._apply_tenant_filter(stmt, tenant_id)
        result = await session.execute(stmt)
        file = result.scalar_one_or_none()

        self._lazy.debug(
            lambda: f"db.get_by_storage_key({storage_key}, tenant={tenant_id}) -> {'found' if file else 'not found'}"
        )
        return file

    async def list_by_owner(
        self,
        session: AsyncSession,
        owner_id: str,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[File]:
        """List files by owner.

        Args:
            session: Database session
            owner_id: Owner identifier
            tenant_id: Optional tenant ID for multi-tenant filtering.
                      If None, no tenant filtering is applied (single-tenant mode).
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of files owned by the user
        """
        stmt = (
            select(File)
            .where(File.owner_id == owner_id)
            .where(File.status != FileStatus.DELETED)
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_tenant_filter(stmt, tenant_id)
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_by_owner: owner_id={owner_id}, tenant={tenant_id}, limit={limit}, offset={offset} -> {len(items)} items"
        )
        return items

    async def list_by_status(
        self,
        session: AsyncSession,
        status: FileStatus,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[File]:
        """List files by status.

        Args:
            session: Database session
            status: File status to filter by
            tenant_id: Optional tenant ID for multi-tenant filtering.
                      If None, no tenant filtering is applied (single-tenant mode).
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of files with the given status
        """
        stmt = (
            select(File)
            .where(File.status == status)
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_tenant_filter(stmt, tenant_id)
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_by_status: status={status.value}, tenant={tenant_id}, limit={limit}, offset={offset} -> {len(items)} items"
        )
        return items

    async def list_expired(
        self,
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        as_of: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[File]:
        """List expired files that should be deleted.

        Args:
            session: Database session
            tenant_id: Optional tenant ID for multi-tenant filtering.
                      If None, no tenant filtering is applied (single-tenant mode).
            as_of: Reference time (defaults to now)
            limit: Maximum results

        Returns:
            Sequence of expired files
        """
        now = as_of or datetime.now(UTC)
        stmt = (
            select(File)
            .where(
                File.expires_at.is_not(None),
                File.expires_at < now,
                File.status != FileStatus.DELETED,
            )
            .order_by(File.expires_at.asc())
            .limit(limit)
        )
        stmt = self._apply_tenant_filter(stmt, tenant_id)
        result = await session.execute(stmt)
        items = result.scalars().all()

        if items:
            self._logger.info(
                "Found expired files",
                extra={
                    "count": len(items),
                    "as_of": now.isoformat(),
                    "tenant_id": tenant_id,
                    "operation": "db.list_expired",
                },
            )
        else:
            self._lazy.debug(lambda: f"db.list_expired: no expired files as of {now} (tenant={tenant_id})")

        return items

    async def search_files(
        self,
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        query: str | None = None,
        owner_id: str | None = None,
        content_type: str | None = None,
        status: FileStatus | None = None,
        is_public: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[File]:
        """Search files with filters.

        Args:
            session: Database session
            tenant_id: Optional tenant ID for multi-tenant filtering.
                      If None, no tenant filtering is applied (single-tenant mode).
            query: Search term (searches filename)
            owner_id: Filter by owner
            content_type: Filter by MIME type (prefix match)
            status: Filter by status
            is_public: Filter by public/private
            limit: Page size
            offset: Results to skip

        Returns:
            SearchResult with files and pagination info
        """
        stmt = select(File)

        # Exclude deleted files by default
        stmt = stmt.where(File.status != FileStatus.DELETED)

        # Apply tenant filter
        stmt = self._apply_tenant_filter(stmt, tenant_id)

        # Text search
        if query:
            stmt = SearchFilter(
                [File.original_filename],
                query,
                case_insensitive=True,
            ).apply(stmt)

        # Owner filter
        if owner_id:
            stmt = stmt.where(File.owner_id == owner_id)

        # Content type filter (prefix match for type/subtype)
        if content_type:
            stmt = stmt.where(File.content_type.startswith(content_type))

        # Status filter
        if status:
            stmt = stmt.where(File.status == status)

        # Public/private filter
        if is_public is not None:
            stmt = stmt.where(File.is_public == is_public)

        # Default ordering
        stmt = stmt.order_by(File.created_at.desc())

        search_result = await self.search(session, stmt, limit=limit, offset=offset)

        self._lazy.debug(
            lambda: f"db.search_files: query={query!r}, owner_id={owner_id}, tenant={tenant_id}, content_type={content_type} "
            f"-> {len(search_result.items)}/{search_result.total}"
        )
        return search_result

    async def update_status(
        self,
        session: AsyncSession,
        file_id: UUID,
        status: FileStatus,
        *,
        tenant_id: str | None = None,
    ) -> File | None:
        """Update file status.

        Args:
            session: Database session
            file_id: File UUID
            status: New status
            tenant_id: Optional tenant ID for multi-tenant verification.
                      If provided, ensures the file belongs to this tenant.
                      If None, no tenant verification is performed.

        Returns:
            Updated file or None if not found (or tenant mismatch)
        """
        file = await self.get_for_tenant(session, file_id, tenant_id)
        if file is None:
            self._lazy.debug(lambda: f"db.update_status({file_id}, tenant={tenant_id}) -> not found")
            return None

        file.status = status
        await session.flush()
        await session.refresh(file)

        self._lazy.debug(lambda: f"db.update_status({file_id}, {status.value}, tenant={tenant_id}) -> success")
        return file

    async def soft_delete(
        self,
        session: AsyncSession,
        file_id: UUID,
        *,
        tenant_id: str | None = None,
    ) -> File | None:
        """Soft delete a file by marking it as deleted.

        Args:
            session: Database session
            file_id: File UUID
            tenant_id: Optional tenant ID for multi-tenant verification.
                      If provided, ensures the file belongs to this tenant.

        Returns:
            Updated file or None if not found (or tenant mismatch)
        """
        return await self.update_status(session, file_id, FileStatus.DELETED, tenant_id=tenant_id)


# Factory function for dependency injection
_file_repository: FileRepository | None = None


def get_file_repository() -> FileRepository:
    """Get FileRepository instance.

    Usage in FastAPI routes:
        >>> from example_service.features.files.repository import (
        ...     FileRepository,
        ...     get_file_repository,
        ... )
        >>>
        >>> @router.get("/{file_id}")
        >>> async def get_file(
        ...     file_id: UUID,
        ...     session: AsyncSession = Depends(get_db_session),
        ...     repo: FileRepository = Depends(get_file_repository),
        ... ):
        ...     return await repo.get_or_raise(session, file_id)
    """
    global _file_repository
    if _file_repository is None:
        _file_repository = FileRepository()
    return _file_repository


__all__ = ["FileRepository", "get_file_repository"]
