"""Compatibility shim for Accent-Auth health provider tests.

The historic import path was ``example_service.features.health.accent_auth_provider``.
Modern code moved helpers under ``.providers.accent_auth`` which broke patch targets.
This module re-exports the helper functions and lazily exposes the provider class
so existing tests keep working.
"""

from __future__ import annotations

from typing import Any

from example_service.core.settings import get_auth_settings
from example_service.infra.auth.accent_auth import get_accent_auth_client

__all__ = ["AccentAuthHealthProvider", "get_accent_auth_client", "get_auth_settings"]  # noqa: F822


def __getattr__(name: str) -> Any:
    if name == "AccentAuthHealthProvider":
        from example_service.features.health.providers.accent_auth import (
            AccentAuthHealthProvider,
        )

        globals()[name] = AccentAuthHealthProvider
        return AccentAuthHealthProvider
    raise AttributeError(name)
