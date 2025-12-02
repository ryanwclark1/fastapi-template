"""Reusable pagination dependencies for FastAPI routes.

This module provides standardized pagination parameters that can be
injected into route handlers via FastAPI's dependency injection system.

Three pagination levels are provided:
    - StandardPagination: Default limits (max 100) for most endpoints
    - ExtendedPagination: Higher limits (max 1000) for admin/audit endpoints
    - SearchPagination: Lower defaults (20) for search results

Usage:
    from example_service.core.dependencies.pagination import (
        StandardPagination,
        PaginationParams,
    )

    @router.get("/items")
    async def list_items(
        pagination: StandardPagination,
    ) -> list[Item]:
        # Use pagination.limit and pagination.offset
        return await get_items(
            limit=pagination.limit,
            offset=pagination.offset,
        )

    # Or with explicit Depends:
    @router.get("/items")
    async def list_items(
        pagination: PaginationParams = Depends(get_standard_pagination),
    ) -> list[Item]:
        ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from example_service.core.settings import get_pagination_settings


class PaginationParams(BaseModel):
    """Standard pagination parameters.

    Attributes:
        limit: Maximum number of items to return.
        offset: Number of items to skip.
    """

    limit: int = Field(ge=1, description="Maximum number of items to return")
    offset: int = Field(ge=0, default=0, description="Number of items to skip")

    model_config = {"frozen": True}


class ExtendedPaginationParams(BaseModel):
    """Extended pagination for admin/audit endpoints.

    Allows higher limits for bulk operations and administrative views.
    """

    limit: int = Field(ge=1, description="Maximum number of items to return")
    offset: int = Field(ge=0, default=0, description="Number of items to skip")

    model_config = {"frozen": True}


class SearchPaginationParams(BaseModel):
    """Search pagination with lower defaults.

    Optimized for search results where fewer items per page
    typically provide better UX and performance.
    """

    limit: int = Field(ge=1, description="Maximum number of search results")
    offset: int = Field(ge=0, default=0, description="Number of results to skip")

    model_config = {"frozen": True}


def get_standard_pagination(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Maximum number of items to return (1-100)",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = 0,
) -> PaginationParams:
    """Get standard pagination parameters.

    Uses settings defaults but enforces maximum from settings.

    Args:
        limit: Maximum items per page (default from settings, max 100).
        offset: Items to skip for pagination.

    Returns:
        PaginationParams with validated limit and offset.
    """
    settings = get_pagination_settings()
    # Enforce max limit from settings
    effective_limit = min(limit, settings.max_limit)
    return PaginationParams(limit=effective_limit, offset=offset)


def get_extended_pagination(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1000,
            description="Maximum number of items to return (1-1000)",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = 0,
) -> ExtendedPaginationParams:
    """Get extended pagination for admin endpoints.

    Allows higher limits for bulk operations and administrative views.

    Args:
        limit: Maximum items per page (default 50, max 1000).
        offset: Items to skip for pagination.

    Returns:
        ExtendedPaginationParams with validated limit and offset.
    """
    settings = get_pagination_settings()
    effective_limit = min(limit, settings.admin_max_limit)
    return ExtendedPaginationParams(limit=effective_limit, offset=offset)


def get_search_pagination(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Maximum number of search results (1-100)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of results to skip"),
    ] = 0,
) -> SearchPaginationParams:
    """Get search-optimized pagination.

    Uses lower defaults for search results where fewer items
    per page typically provide better UX.

    Args:
        limit: Maximum results per page (default 20, max 100).
        offset: Results to skip for pagination.

    Returns:
        SearchPaginationParams with validated limit and offset.
    """
    settings = get_pagination_settings()
    effective_limit = min(limit, settings.max_limit)
    return SearchPaginationParams(limit=effective_limit, offset=offset)


# Type aliases for cleaner route signatures
StandardPagination = Annotated[PaginationParams, Depends(get_standard_pagination)]
ExtendedPagination = Annotated[ExtendedPaginationParams, Depends(get_extended_pagination)]
SearchPagination = Annotated[SearchPaginationParams, Depends(get_search_pagination)]
