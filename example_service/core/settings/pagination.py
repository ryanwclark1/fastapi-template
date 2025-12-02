"""Pagination settings for API responses.

This module provides configurable defaults for pagination across all API endpoints.
Having centralized pagination settings ensures consistency and allows easy tuning
based on performance requirements.

Environment variables use PAGINATION_ prefix.
Example: PAGINATION_DEFAULT_LIMIT=50, PAGINATION_MAX_LIMIT=100
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PaginationSettings(BaseSettings):
    """Pagination configuration settings.

    These settings control default and maximum values for paginated
    API responses across the application.

    Attributes:
        default_limit: Default number of items per page when not specified.
        max_limit: Maximum allowed items per page (hard limit).
        search_default_limit: Default limit for search results (typically lower).
        cursor_page_size: Default page size for cursor-based pagination.

    Example:
        settings = PaginationSettings()
        # Use in route:
        limit = min(requested_limit, settings.max_limit)
    """

    default_limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Default page size when limit not specified",
    )
    max_limit: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum allowed page size (hard limit)",
    )
    search_default_limit: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Default page size for search results",
    )
    cursor_page_size: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Default page size for cursor-based pagination",
    )
    admin_max_limit: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum page size for admin/audit endpoints",
    )

    model_config = SettingsConfigDict(
        env_prefix="PAGINATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
    )
