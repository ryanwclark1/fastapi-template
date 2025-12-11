"""Accent-Auth utility functions.

This module provides pure utility functions for working with Accent-Auth
data models. These functions are Protocol-agnostic and can be used with
any AuthClient implementation (HttpAuthClient, DatabaseAuthClient, MockAuthClient).

Key Principles:
    - Pure functions (no side effects)
    - No dependencies on specific AuthClient implementations
    - Single responsibility (one function = one transformation)
    - Type-safe with full type annotations

Pattern: Utility module with pure functions (similar to storage/utils, messaging/utils)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from example_service.core.schemas.auth import AuthUser

if TYPE_CHECKING:
    from example_service.infra.auth.models import AccentAuthToken


def to_auth_user(token_info: AccentAuthToken) -> AuthUser:
    """Convert Accent-Auth token to AuthUser model.

    This is a pure function that transforms an AccentAuthToken (from any
    AuthClient implementation) into the application's AuthUser schema.
    The conversion is deterministic and has no side effects.

    The function extracts:
    - User ID from token metadata
    - ACL permissions from token
    - Additional metadata (tenant, session, auth_id, etc.)

    Args:
        token_info: Accent-Auth token information from AuthClient.validate_token()

    Returns:
        AuthUser model suitable for FastAPI dependencies and route handlers

    Example:
        # With any AuthClient implementation
        client = get_auth_client()  # HttpAuthClient or DatabaseAuthClient
        token_info = await client.validate_token("token-uuid")
        auth_user = to_auth_user(token_info)

        # Now use in routes
        @router.get("/profile")
        async def get_profile(user: AuthUser):
            return {"user_id": user.user_id}

    Note:
        This function is used internally by the get_auth_user() dependency
        to convert validated tokens into the AuthUser schema that routes
        expect. You typically won't call this directly.
    """
    return AuthUser(
        user_id=token_info.metadata.uuid,
        service_id=None,  # Not applicable for Accent-Auth tokens
        email=None,  # Email not included in token metadata
        roles=[],  # Accent-Auth uses ACL-based permissions, not roles
        permissions=token_info.acl,  # ACL list from token
        acl={},  # ACL dict built from permissions in can_access_resource (legacy)
        metadata={
            "tenant_uuid": token_info.metadata.tenant_uuid,
            "auth_id": token_info.metadata.auth_id or token_info.auth_id,
            "session_uuid": token_info.session_uuid,
            "token": token_info.token,
            "expires_at": token_info.expires_at,
            "accent_uuid": token_info.accent_uuid,
        },
    )


__all__ = [
    "to_auth_user",
]
