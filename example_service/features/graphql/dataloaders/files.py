"""DataLoaders for batch-loading files and thumbnails.

Prevents N+1 queries when resolving file and thumbnail references.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.files.models import File, FileThumbnail

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FileDataLoader:
    """DataLoader for batch-loading files by ID.

    Prevents N+1 queries when resolving file references.
    Each request gets its own loader instance for proper caching.

    Usage:
        loader = FileDataLoader(session)
        file = await loader.load(uuid)
        files = await loader.load_many([uuid1, uuid2, uuid3])
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, File | None] = DataLoader(load_fn=self._batch_load_files)

    async def _batch_load_files(
        self,
        ids: list[UUID],
    ) -> list[File | None]:
        """Batch load files by IDs.

        Args:
            ids: List of file UUIDs to load

        Returns:
            List of File objects (or None) in same order as ids
        """
        if not ids:
            return []

        # Single query for all IDs
        stmt = select(File).where(File.id.in_(ids))
        result = await self._session.execute(stmt)
        files = {f.id: f for f in result.scalars().all()}

        # Return in same order as requested, None for missing
        return [files.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> File | None:
        """Load a single file by ID.

        Args:
            id_: File UUID

        Returns:
            File if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[File | None]:
        """Load multiple files by IDs.

        Args:
            ids: List of file UUIDs

        Returns:
            List of File objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class FileThumbnailDataLoader:
    """DataLoader for batch-loading file thumbnails by ID.

    Prevents N+1 queries when resolving thumbnail references.

    Usage:
        loader = FileThumbnailDataLoader(session)
        thumbnail = await loader.load(uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, FileThumbnail | None] = DataLoader(
            load_fn=self._batch_load_thumbnails,
        )

    async def _batch_load_thumbnails(
        self,
        ids: list[UUID],
    ) -> list[FileThumbnail | None]:
        """Batch load thumbnails by IDs.

        Args:
            ids: List of thumbnail UUIDs to load

        Returns:
            List of FileThumbnail objects (or None) in same order as ids
        """
        if not ids:
            return []

        stmt = select(FileThumbnail).where(FileThumbnail.id.in_(ids))
        result = await self._session.execute(stmt)
        thumbnails = {t.id: t for t in result.scalars().all()}

        return [thumbnails.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> FileThumbnail | None:
        """Load a single thumbnail by ID.

        Args:
            id_: Thumbnail UUID

        Returns:
            FileThumbnail if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[FileThumbnail | None]:
        """Load multiple thumbnails by IDs.

        Args:
            ids: List of thumbnail UUIDs

        Returns:
            List of FileThumbnail objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


class FileThumbnailsByFileDataLoader:
    """DataLoader for batch-loading thumbnails by file ID.

    Solves N+1 problem when loading thumbnails for multiple files.
    Maps file_id -> list of thumbnails.

    Usage:
        loader = FileThumbnailsByFileDataLoader(session)
        thumbnails = await loader.load(file_uuid)  # Returns list[FileThumbnail]
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, list[FileThumbnail]] = DataLoader(
            load_fn=self._batch_load_thumbnails_by_file,
        )

    async def _batch_load_thumbnails_by_file(
        self,
        file_ids: list[UUID],
    ) -> list[list[FileThumbnail]]:
        """Batch load thumbnails for multiple files.

        Args:
            file_ids: List of file UUIDs

        Returns:
            List of thumbnail lists, one per file_id (empty list if none)
        """
        if not file_ids:
            return []

        # Single query for all thumbnails
        stmt = select(FileThumbnail).where(FileThumbnail.file_id.in_(file_ids))
        result = await self._session.execute(stmt)
        all_thumbnails = result.scalars().all()

        # Group by file_id
        thumbnails_by_file: dict[UUID, list[FileThumbnail]] = {fid: [] for fid in file_ids}
        for thumbnail in all_thumbnails:
            thumbnails_by_file.setdefault(thumbnail.file_id, []).append(thumbnail)

        # Return in same order as requested
        return [thumbnails_by_file.get(fid, []) for fid in file_ids]

    async def load(self, file_id: UUID) -> list[FileThumbnail]:
        """Load thumbnails for a single file.

        Args:
            file_id: File UUID

        Returns:
            List of thumbnails for the file (empty list if none)
        """
        return await self._loader.load(file_id)

    async def load_many(self, file_ids: list[UUID]) -> list[list[FileThumbnail]]:
        """Load thumbnails for multiple files.

        Args:
            file_ids: List of file UUIDs

        Returns:
            List of thumbnail lists, one per file_id
        """
        return await self._loader.load_many(file_ids)


__all__ = ["FileDataLoader", "FileThumbnailDataLoader", "FileThumbnailsByFileDataLoader"]
