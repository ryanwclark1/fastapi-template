"""Items service layer."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.models.item import Item
from example_service.core.services.base import BaseService
from example_service.features.items.schemas import ItemCreate, ItemUpdate

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ItemService(BaseService):
    """Service for managing items.

    Demonstrates CRUD operations, pagination, filtering, and caching.
    """

    async def create_item(
        self, session: AsyncSession, data: ItemCreate, owner_id: str
    ) -> Item:
        """Create a new item.

        Args:
            session: Database session.
            data: Item creation data.
            owner_id: ID of the item owner.

        Returns:
            Created item.

        Example:
            ```python
            item = await service.create_item(
                session, ItemCreate(title="Task"), "user-123"
            )
            ```
        """
        item = Item(
            title=data.title,
            description=data.description,
            is_completed=data.is_completed,
            owner_id=owner_id,
        )

        session.add(item)
        await session.flush()
        await session.refresh(item)

        logger.info(f"Created item {item.id} for owner {owner_id}")
        return item

    async def get_item(
        self, session: AsyncSession, item_id: UUID, owner_id: str
    ) -> Item | None:
        """Get item by ID.

        Args:
            session: Database session.
            item_id: Item UUID.
            owner_id: Owner ID for access control.

        Returns:
            Item if found and owned by user, None otherwise.
        """
        stmt = select(Item).where(
            Item.id == item_id,
            Item.owner_id == owner_id,
            Item.is_deleted == False,  # noqa: E712
        )

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_items(
        self,
        session: AsyncSession,
        owner_id: str,
        *,
        page: int = 1,
        page_size: int = 10,
        completed: bool | None = None,
    ) -> tuple[list[Item], int]:
        """List items with pagination and filtering.

        Args:
            session: Database session.
            owner_id: Owner ID for filtering.
            page: Page number (1-indexed).
            page_size: Items per page.
            completed: Filter by completion status (None = all).

        Returns:
            Tuple of (items list, total count).

        Example:
            ```python
            items, total = await service.list_items(
                session, "user-123", page=1, page_size=20, completed=False
            )
            ```
        """
        # Base query
        stmt = select(Item).where(
            Item.owner_id == owner_id,
            Item.is_deleted == False,  # noqa: E712
        )

        # Apply filters
        if completed is not None:
            stmt = stmt.where(Item.is_completed == completed)

        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Apply pagination
        stmt = stmt.order_by(Item.created_at.desc())
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)

        # Execute
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def update_item(
        self,
        session: AsyncSession,
        item_id: UUID,
        owner_id: str,
        data: ItemUpdate,
    ) -> Item | None:
        """Update an existing item.

        Args:
            session: Database session.
            item_id: Item UUID.
            owner_id: Owner ID for access control.
            data: Update data (partial update).

        Returns:
            Updated item if found, None otherwise.
        """
        item = await self.get_item(session, item_id, owner_id)
        if not item:
            return None

        # Apply updates (only non-None fields)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)

        await session.flush()
        await session.refresh(item)

        logger.info(f"Updated item {item_id}")
        return item

    async def delete_item(
        self, session: AsyncSession, item_id: UUID, owner_id: str
    ) -> bool:
        """Soft delete an item.

        Args:
            session: Database session.
            item_id: Item UUID.
            owner_id: Owner ID for access control.

        Returns:
            True if deleted, False if not found.
        """
        item = await self.get_item(session, item_id, owner_id)
        if not item:
            return False

        item.is_deleted = True
        await session.flush()

        logger.info(f"Deleted item {item_id}")
        return True
