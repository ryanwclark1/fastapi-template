"""DEPRECATED: Base database model classes.

This module is deprecated and kept only for backward compatibility.
All new code should import from example_service.core.database instead.

Deprecated in: Phase 1 of database architecture refactor
Will be removed in: Future major version

Migration Guide:
    Old:
        from example_service.infra.database.base import Base, TimestampedBase

    New:
        from example_service.core.database import Base, TimestampedBase

The new core.database package provides enhanced features:
    - Flexible primary key mixins (IntegerPKMixin, UUIDPKMixin)
    - Audit columns (created_by, updated_by)
    - Soft delete support
    - Automatic table name generation
    - Repository pattern with BaseRepository

See: example_service/core/database/base.py for full documentation
"""
from __future__ import annotations

import warnings

# Import from new location
from example_service.core.database.base import (
    NAMING_CONVENTION,
    Base,
    TimestampedBase,
)

# Show deprecation warning once per session
warnings.warn(
    "example_service.infra.database.base is deprecated. "
    "Use example_service.core.database instead. "
    "The infra.database package should only contain session/connection management.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "Base",
    "TimestampedBase",
    "NAMING_CONVENTION",
]
