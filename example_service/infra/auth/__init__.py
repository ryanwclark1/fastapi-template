"""Authentication infrastructure for Accent-Auth integration.

This module provides authentication via the accent-auth-client library:
- Token validation with Accent-Auth API
- ACL-based authorization with wildcards and negation
- Multi-tenant support via Accent-Tenant header
- Reserved word substitution (me, my_session)

The accent-auth-client library is optional. If not installed, a fallback
HTTP client is used for basic token operations.

Installation:
    pip install accent-auth-client
"""

from __future__ import annotations

from .accent_auth import (
    ACCENT_AUTH_CLIENT_AVAILABLE,
    AccentAuthACL,
    AccentAuthClient,
    AccentAuthMetadata,
    AccentAuthToken,
    get_accent_auth_client,
)

__all__ = [
    "ACCENT_AUTH_CLIENT_AVAILABLE",
    "AccentAuthACL",
    "AccentAuthClient",
    "AccentAuthMetadata",
    "AccentAuthToken",
    "get_accent_auth_client",
]
