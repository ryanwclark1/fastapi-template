"""Service layer for the tags feature."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.database import NotFoundError
from example_service.core.exceptions import ConflictException
from example_service.features.tags.models import Tag
from example_service.features.tags.repository import TagRepository, get_tag_repository
from example_service.infra.logging import get_lazy_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.features.tags.schemas import TagCreate, TagUpdate


# Standard logger for INFO/WARNING/ERROR
logger = logging.getLogger(__name__)
# Lazy logger for DEBUG (zero overhead when DEBUG disabled)
lazy_logger = get_lazy_logger(__name__)


class TagService:
    """Service for tag management operations.

    Handles business logic for:
    - Tag CRUD operations
    - Name uniqueness validation
    - Reminder count retrieval
    """

    def __init__(
        self,
        session: AsyncSession,
        repo: TagRepository | None = None,
    ) -> None:
        """Initialize the tag service.

        Args:
            session: Database session for operations
            repo: Tag repository (optional, uses default if not provided)
        """
        self._session = session
        self._repo = repo or get_tag_repository()

    async def list_tags(
        self,
        *,
        search: str | None = None,
        include_counts: bool = False,
    ) -> tuple[Sequence[Tag], dict[UUID, int]]:
        """List tags with optional search and counts.

        Args:
            search: Filter tags by name (case-insensitive contains)
            include_counts: Include reminder counts per tag

        Returns:
            Tuple of (tags, counts_dict). If include_counts is False,
            counts_dict will be empty.
        """
        tags = await self._repo.list_with_search(self._session, search=search)

        counts: dict[UUID, int] = {}
        if include_counts:
            counts = await self._repo.get_reminder_counts(self._session)

        lazy_logger.debug(
            lambda: f"service.list_tags(search={search!r}, include_counts={include_counts}) "
            f"-> {len(tags)} tags",
        )
        return tags, counts

    async def get_tag(self, tag_id: UUID) -> Tag:
        """Get a tag by ID.

        Args:
            tag_id: Tag UUID

        Returns:
            The tag

        Raises:
            NotFoundError: If tag not found
        """
        tag = await self._repo.get(self._session, tag_id)
        if tag is None:
            msg = "Tag"
            raise NotFoundError(msg, {"id": str(tag_id)})

        lazy_logger.debug(lambda: f"service.get_tag({tag_id}) -> found")
        return tag

    async def get_tag_with_count(self, tag_id: UUID) -> tuple[Tag, int]:
        """Get a tag with its reminder count.

        Args:
            tag_id: Tag UUID

        Returns:
            Tuple of (tag, reminder_count)

        Raises:
            NotFoundError: If tag not found
        """
        tag = await self.get_tag(tag_id)
        count = await self._repo.get_reminder_count_for_tag(self._session, tag_id)

        lazy_logger.debug(
            lambda: f"service.get_tag_with_count({tag_id}) -> count={count}",
        )
        return tag, count

    async def create_tag(self, payload: TagCreate) -> Tag:
        """Create a new tag.

        Args:
            payload: Tag creation data

        Returns:
            Created tag

        Raises:
            ConflictException: If tag name already exists
        """
        # Check for existing tag with same name
        existing = await self._repo.get_by_name(self._session, payload.name)
        if existing:
            raise ConflictException(
                detail=f"Tag with name '{payload.name}' already exists",
                type="tag-name-exists",
                extra={"name": payload.name},
            )

        tag = Tag(
            name=payload.name,
            color=payload.color,
            description=payload.description,
        )

        created = await self._repo.create(self._session, tag)

        logger.info(
            "Tag created",
            extra={"tag_id": str(created.id), "tag_name": created.name},
        )
        return created

    async def update_tag(self, tag_id: UUID, payload: TagUpdate) -> Tag:
        """Update an existing tag.

        Args:
            tag_id: Tag UUID
            payload: Update data

        Returns:
            Updated tag

        Raises:
            NotFoundError: If tag not found
            ConflictException: If new name conflicts with existing tag
        """
        tag = await self.get_tag(tag_id)

        # Check for name conflict if changing name
        if payload.name is not None and payload.name != tag.name:
            existing = await self._repo.get_by_name(self._session, payload.name)
            if existing:
                raise ConflictException(
                    detail=f"Tag with name '{payload.name}' already exists",
                    type="tag-name-exists",
                    extra={"name": payload.name},
                )
            tag.name = payload.name

        if payload.color is not None:
            tag.color = payload.color

        if payload.description is not None:
            tag.description = payload.description

        await self._session.flush()
        await self._session.refresh(tag)

        lazy_logger.debug(lambda: f"service.update_tag({tag_id}) -> updated")
        return tag

    async def delete_tag(self, tag_id: UUID) -> None:
        """Delete a tag.

        Args:
            tag_id: Tag UUID

        Raises:
            NotFoundError: If tag not found
        """
        tag = await self.get_tag(tag_id)
        await self._repo.delete(self._session, tag)

        logger.info(
            "Tag deleted",
            extra={"tag_id": str(tag_id)},
        )

    async def get_tags_by_ids(
        self,
        tag_ids: list[UUID],
        *,
        raise_if_missing: bool = True,
    ) -> Sequence[Tag]:
        """Get multiple tags by their IDs.

        Args:
            tag_ids: List of tag UUIDs
            raise_if_missing: If True, raise NotFoundError for missing tags

        Returns:
            Sequence of found tags

        Raises:
            NotFoundError: If raise_if_missing and some tags not found
        """
        if not tag_ids:
            return []

        tags = await self._repo.get_tags_by_ids(self._session, tag_ids)

        if raise_if_missing:
            found_ids = {tag.id for tag in tags}
            missing = set(tag_ids) - found_ids
            if missing:
                msg = "Tag"
                raise NotFoundError(msg, {"ids": [str(id) for id in missing]})

        return tags
