"""Cache warming and management tasks.

This module provides:
- Cache warming to pre-populate frequently accessed data
- Cache invalidation by pattern
"""

from __future__ import annotations

try:
    from .tasks import invalidate_cache_pattern, warm_cache
except ImportError:
    warm_cache = None  # type: ignore[assignment]
    invalidate_cache_pattern = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "invalidate_cache_pattern",
        "warm_cache",
    ]
