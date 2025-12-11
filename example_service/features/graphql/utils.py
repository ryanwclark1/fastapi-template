"""GraphQL utility functions for permission checking and ACL management.

This module provides reusable utility functions for GraphQL permission classes,
centralizing common patterns and reducing code duplication.

The utilities are auth-mode agnostic - they work whether the AuthUser came from:
- DatabaseAuthClient (internal mode - direct database access)
- HttpAuthClient (external mode - HTTP calls to accent-auth)
- MockAuthClient (testing mode - no external dependencies)

Key Functions:
    - create_acl_checker(): Create AccentAuthACL from AuthUser context

Example:
    ```python
    from example_service.features.graphql.utils import create_acl_checker
    from example_service.core.schemas.auth import AuthUser

    def has_permission(self, _source: Any, info: Info, **_kwargs: Any) -> bool:
        user = info.context.user
        if not user:
            return False

        # Single line instead of 8 lines of boilerplate!
        acl = create_acl_checker(user)

        return acl.has_permission(self.acl_pattern)
    ```

Pattern: Utility module with pure functions (similar to core/utils/acl.py)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser
    from example_service.infra.auth.accent_auth import AccentAuthACL


def create_acl_checker(user: AuthUser) -> AccentAuthACL:
    """Create ACL checker from authenticated user context.

    Centralizes the pattern repeated across GraphQL permission classes.
    This helper extracts session and tenant context from the user metadata
    and initializes an AccentAuthACL instance with full context for:

    - Permission checking with wildcards (*, #)
    - Reserved word substitution (me, my_session, my_tenant)
    - Tenant-aware ACL validation
    - Negation patterns (! prefix)

    This function is auth-mode agnostic - it works regardless of how the
    AuthUser was obtained (DatabaseAuthClient, HttpAuthClient, or MockAuthClient).

    Args:
        user: Authenticated user from GraphQL context (info.context.user)

    Returns:
        AccentAuthACL instance configured with user's permissions and context

    Example:
        ```python
        # In a permission class:
        def has_permission(self, _source: Any, info: Info, **_kwargs: Any) -> bool:
            user = info.context.user
            if not user:
                return False

            # Create ACL checker with full context
            acl = create_acl_checker(user)

            # Check permission
            if not acl.has_permission("confd.users.read"):
                return False

            return True
        ```

    Note:
        This function is used internally by GraphQL permission classes to avoid
        duplicating the 8-line ACL initialization pattern. It consolidates:
        - Session ID extraction from metadata
        - Tenant ID extraction from metadata
        - AccentAuthACL initialization with full context
    """
    from example_service.infra.auth.accent_auth import AccentAuthACL

    # Extract context from user metadata
    session_id = user.metadata.get("session_uuid") or user.metadata.get("token")
    tenant_id = user.metadata.get("tenant_uuid")

    # Create ACL checker with full user context
    return AccentAuthACL(
        user.permissions,
        auth_id=user.user_id,
        session_id=session_id,
        tenant_id=tenant_id,
    )


__all__ = [
    "create_acl_checker",
]
