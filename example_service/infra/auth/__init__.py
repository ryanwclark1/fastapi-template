"""Authentication infrastructure for Accent-Auth integration.

This module provides authentication via Accent-Auth service:
- Token validation with Accent-Auth API
- ACL-based authorization with wildcards
- Multi-tenant support via Accent-Tenant header
"""

from __future__ import annotations

from .accent_auth import (
    AccentAuthACL,
    AccentAuthClient,
    AccentAuthMetadata,
    AccentAuthSession,
    AccentAuthToken,
    get_accent_auth_client,
)

__all__ = [
    "AccentAuthACL",
    "AccentAuthClient",
    "AccentAuthMetadata",
    "AccentAuthSession",
    "AccentAuthToken",
    "get_accent_auth_client",
]
