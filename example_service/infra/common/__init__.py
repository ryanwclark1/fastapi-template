"""Common infrastructure utilities.

This module provides shared utilities for infrastructure components:
- InfraResult: Unified result type for infrastructure operations
- ProviderRegistry: Lightweight mixin for provider registration patterns

These utilities help reduce code duplication while keeping domain-specific
logic where it belongs.
"""

from __future__ import annotations

from .result import InfraResult

__all__ = [
    "InfraResult",
]
