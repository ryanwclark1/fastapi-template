"""Items API router."""
from __future__ import annotations

import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_session
from example_service.features.items.schemas import (
    ItemCreate,
    ItemListResponse,
    ItemResponse,
    ItemUpdate,
)
from example_service.features.items.service import ItemService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])


def get_item_service() -> ItemService:
    """Get item service dependency."""
    return ItemService()


# Mock auth - in real app, use proper auth dependency
def get_current_user_id() -> str:
    """Get current user ID (mock).

    In production, replace with proper authentication.
    """
    return "demo-user"


@router.post(
    "/",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new item",
)
async def create_item(
    data: ItemCreate,
    session: AsyncSession = Depends(get_session),
    service: ItemService = Depends(get_item_service),
    user_id: str = Depends(get_current_user_id),
) -> ItemResponse:
    """Create a new item.

    Args:
        data: Item creation data.
        session: Database session.
        service: Item service.
        user_id: Current user ID.

    Returns:
        Created item.

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v1/items/ \\
          -H "Content-Type: application/json" \\
          -d '{"title": "Buy groceries", "description": "Milk and eggs"}'
        ```
    """
    item = await service.create_item(session, data, user_id)
    await session.commit()

    return ItemResponse.model_validate(item)


@router.get(
    "/",
    response_model=ItemListResponse,
    summary="List items",
)
async def list_items(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    completed: bool | None = Query(None, description="Filter by completion status"),
    session: AsyncSession = Depends(get_session),
    service: ItemService = Depends(get_item_service),
    user_id: str = Depends(get_current_user_id),
) -> ItemListResponse:
    """List items with pagination and filtering.

    Args:
        page: Page number (1-indexed).
        page_size: Items per page (max 100).
        completed: Filter by completion status.
        session: Database session.
        service: Item service.
        user_id: Current user ID.

    Returns:
        Paginated list of items.

    Example:
        ```bash
        # Get first page
        curl http://localhost:8000/api/v1/items/

        # Get completed items
        curl "http://localhost:8000/api/v1/items/?completed=true"

        # Get page 2 with 20 items
        curl "http://localhost:8000/api/v1/items/?page=2&page_size=20"
        ```
    """
    items, total = await service.list_items(
        session, user_id, page=page, page_size=page_size, completed=completed
    )

    pages = math.ceil(total / page_size) if total > 0 else 1

    return ItemListResponse(
        items=[ItemResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/{item_id}",
    response_model=ItemResponse,
    summary="Get item by ID",
)
async def get_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: ItemService = Depends(get_item_service),
    user_id: str = Depends(get_current_user_id),
) -> ItemResponse:
    """Get item by ID.

    Args:
        item_id: Item UUID.
        session: Database session.
        service: Item service.
        user_id: Current user ID.

    Returns:
        Item details.

    Raises:
        HTTPException: 404 if item not found.

    Example:
        ```bash
        curl http://localhost:8000/api/v1/items/123e4567-e89b-12d3-a456-426614174000
        ```
    """
    item = await service.get_item(session, item_id, user_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )

    return ItemResponse.model_validate(item)


@router.patch(
    "/{item_id}",
    response_model=ItemResponse,
    summary="Update item",
)
async def update_item(
    item_id: UUID,
    data: ItemUpdate,
    session: AsyncSession = Depends(get_session),
    service: ItemService = Depends(get_item_service),
    user_id: str = Depends(get_current_user_id),
) -> ItemResponse:
    """Update an existing item (partial update).

    Args:
        item_id: Item UUID.
        data: Update data.
        session: Database session.
        service: Item service.
        user_id: Current user ID.

    Returns:
        Updated item.

    Raises:
        HTTPException: 404 if item not found.

    Example:
        ```bash
        curl -X PATCH http://localhost:8000/api/v1/items/123e4567... \\
          -H "Content-Type: application/json" \\
          -d '{"is_completed": true}'
        ```
    """
    item = await service.update_item(session, item_id, user_id, data)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )

    await session.commit()
    return ItemResponse.model_validate(item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete item",
)
async def delete_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: ItemService = Depends(get_item_service),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Delete an item (soft delete).

    Args:
        item_id: Item UUID.
        session: Database session.
        service: Item service.
        user_id: Current user ID.

    Raises:
        HTTPException: 404 if item not found.

    Example:
        ```bash
        curl -X DELETE http://localhost:8000/api/v1/items/123e4567...
        ```
    """
    deleted = await service.delete_item(session, item_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )

    await session.commit()
