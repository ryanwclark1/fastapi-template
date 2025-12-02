"""Utility modules for common operations.

This package provides reusable utilities for:
- Field updates with change tracking
- Retry patterns
- Common helpers
"""

from example_service.utils.updates import (
    UpdateResult,
    apply_update_if_changed,
    apply_updates,
)

__all__ = [
    "UpdateResult",
    "apply_update_if_changed",
    "apply_updates",
]
