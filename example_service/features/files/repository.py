"""Repository for the files feature."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from example_service.core.database import SearchFilter
from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.features.files.models import File, FileStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FileRepository(BaseRepository[File]):
    """Repository for File model.

    Inherits from BaseRepository:
        - get(session, id) -> File | None
        - get_or_raise(session, id) -> File
        - get_by(session, attr, value) -> File | None
        - list(session, limit, offset) -> Sequence[File]
        - search(session, statement, limit, offset) -> SearchResult[File]
        - create(session, instance) -> File
        - create_many(session, instances) -> Sequence[File]
        - delete(session, instance) -> None

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with File model."""
        super().__init__(File)

    async def get_by_storage_key(
        self,
        session: AsyncSession,
        storage_key: str,
    ) -> File | None:
        """Get file by its storage key.

        Args:
            session: Database session
            storage_key: S3 storage key

        Returns:
            File if found, None otherwise
        """
        stmt = select(File).where(File.storage_key == storage_key)
        result = await session.execute(stmt)
        file = result.scalar_one_or_none()

        self._lazy.debug(
            lambda: f"db.get_by_storage_key({storage_key}) -> {'found' if file else 'not found'}"
        )
        return file

    async def list_by_owner(
        self,
        session: AsyncSession,
        owner_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[File]:
        """List files by owner.

        Args:
            session: Database session
            owner_id: Owner identifier
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
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_by_owner: owner_id={owner_id}, limit={limit}, offset={offset} -> {len(items)} items"
        )
        return items

    async def list_by_status(
        self,
        session: AsyncSession,
        status: FileStatus,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[File]:
        """List files by status.

        Args:
            session: Database session
            status: File status to filter by
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
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_by_status: status={status.value}, limit={limit}, offset={offset} -> {len(items)} items"
        )
        return items

    async def list_expired(
        self,
        session: AsyncSession,
        *,
        as_of: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[File]:
        """List expired files that should be deleted.

        Args:
            session: Database session
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
        result = await session.execute(stmt)
        items = result.scalars().all()

        if items:
            self._logger.info(
                "Found expired files",
                extra={
                    "count": len(items),
                    "as_of": now.isoformat(),
                    "operation": "db.list_expired",
                },
            )
        else:
            self._lazy.debug(lambda: f"db.list_expired: no expired files as of {now}")

        return items

    async def search_files(
        self,
        session: AsyncSession,
        *,
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
            lambda: f"db.search_files: query={query!r}, owner_id={owner_id}, content_type={content_type} "
            f"-> {len(search_result.items)}/{search_result.total}"
        )
        return search_result

    async def update_status(
        self,
        session: AsyncSession,
        file_id: UUID,
        status: FileStatus,
    ) -> File | None:
        """Update file status.

        Args:
            session: Database session
            file_id: File UUID
            status: New status

        Returns:
            Updated file or None if not found
        """
        file = await self.get(session, file_id)
        if file is None:
            self._lazy.debug(lambda: f"db.update_status({file_id}) -> not found")
            return None

        file.status = status
        await session.flush()
        await session.refresh(file)

        self._lazy.debug(lambda: f"db.update_status({file_id}, {status.value}) -> success")
        return file

    async def soft_delete(
        self,
        session: AsyncSession,
        file_id: UUID,
    ) -> File | None:
        """Soft delete a file by marking it as deleted.

        Args:
            session: Database session
            file_id: File UUID

        Returns:
            Updated file or None if not found
        """
        return await self.update_status(session, file_id, FileStatus.DELETED)


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
