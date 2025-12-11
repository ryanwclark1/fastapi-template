"""Utilities for tracking imports that must remain at runtime.

FastAPI and Pydantic evaluate annotations using module-level globals. When
`from __future__ import annotations` is active, those annotations are stored as
strings (e.g. ``"datetime.datetime | None"``). When FastAPI later resolves
dependencies it expects the referenced modules (``datetime`` in this example)
to exist in the module namespace. Ruff's TC00x rules flag these imports as
type-only because they often appear only in annotations.

This helper provides a declarative way to mark such imports as intentional
runtime dependencies without sprinkling ``# noqa`` comments everywhere.
"""

from __future__ import annotations

from typing import Any

__all__ = ["require_runtime_dependency"]

# Keep a module-level reference so the runtime still holds on to the objects.
_RUNTIME_DEPENDENCIES: list[Any] = []


def require_runtime_dependency(*dependencies: Any) -> None:
    """Record dependencies that are required during runtime.

    Args:
        dependencies: Objects (modules, classes, functions) that must remain
            importable at runtime even if they appear type-only to static
            analyzers.
    """
    for dependency in dependencies:
        if dependency is None:
            continue
        _RUNTIME_DEPENDENCIES.append(dependency)
