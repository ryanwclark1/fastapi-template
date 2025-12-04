"""Programmatic ACL checker for use in business logic.

While require_acl() dependency is preferred for route protection,
this class provides a way to check ACLs within service methods
and business logic when more complex permission checks are needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.core.acl.access_check import get_cached_access_check

if TYPE_CHECKING:
    from example_service.core.schemas.auth import TokenPayload

__all__ = ["ACLChecker"]


class ACLChecker:
    """Reusable ACL checker for programmatic permission checks.

    Use this class when you need to check permissions within business
    logic, not just at the route level. The checker wraps a validated
    token and provides convenient methods for common ACL operations.

    Example:
        >>> async def transfer_ownership(
        ...     token: TokenPayload,
        ...     resource_id: str,
        ...     new_owner_id: str,
        ... ):
        ...     checker = ACLChecker(token)
        ...
        ...     # Must have admin OR be current owner
        ...     if not checker.has_any_acl(
        ...         "admin.resources.*",
        ...         f"resources.{resource_id}.transfer",
        ...     ):
        ...         raise PermissionError("Cannot transfer resource")
        ...
        ...     return await do_transfer(resource_id, new_owner_id)

    Note:
        For simple route protection, prefer using require_acl() dependency:

        @router.post("/resources/{id}/transfer")
        async def transfer(
            _: Annotated[TokenPayload, Depends(require_acl("resources.{id}.transfer"))]
        ):
            ...
    """

    def __init__(self, token: TokenPayload | Any) -> None:
        """Initialize ACL checker for a validated token.

        Args:
            token: Validated token payload containing ACL list.
                   Must have 'sub' (auth_id), 'session_id', and 'acl' attributes.
        """
        self.token = token
        # Use cached factory for optimal performance
        self._checker = get_cached_access_check(
            getattr(token, "sub", None) or getattr(token, "auth_id", None),
            getattr(token, "session_id", None),
            getattr(token, "acl", None) or [],
        )

    def has_acl(self, pattern: str) -> bool:
        """Check if token has a specific ACL pattern.

        Args:
            pattern: ACL pattern to check (e.g., "users.123.read")

        Returns:
            True if token's ACLs match the pattern
        """
        return self._checker.matches_required_access(pattern)

    def has_any_acl(self, *patterns: str) -> bool:
        """Check if token has ANY of the specified ACL patterns.

        Useful for "OR" permission checks where multiple patterns
        could grant access.

        Args:
            *patterns: ACL patterns to check

        Returns:
            True if token matches at least one pattern

        Example:
            >>> # User can read if they're admin OR owner
            >>> checker.has_any_acl("admin.users.*", f"users.{user_id}.read")
        """
        return any(self.has_acl(pattern) for pattern in patterns)

    def has_all_acls(self, *patterns: str) -> bool:
        """Check if token has ALL of the specified ACL patterns.

        Useful for operations requiring multiple permissions.

        Args:
            *patterns: ACL patterns to check

        Returns:
            True if token matches all patterns

        Example:
            >>> # User must have both read AND write permissions
            >>> checker.has_all_acls(
            ...     f"documents.{doc_id}.read",
            ...     f"documents.{doc_id}.write",
            ... )
        """
        return all(self.has_acl(pattern) for pattern in patterns)

    def is_superuser(self) -> bool:
        """Check if token has superuser access (# wildcard).

        The '#' pattern grants recursive access to everything.

        Returns:
            True if token has # ACL
        """
        return self.has_acl("#")

    def get_matching_patterns(self, *patterns: str) -> list[str]:
        """Get list of patterns that match the token's ACLs.

        Useful for determining which of several possible permissions
        the user actually has.

        Args:
            *patterns: Patterns to check

        Returns:
            List of patterns that matched
        """
        return [pattern for pattern in patterns if self.has_acl(pattern)]

    def get_failed_patterns(self, *patterns: str) -> list[str]:
        """Get list of patterns that do NOT match the token's ACLs.

        Useful for error messages explaining missing permissions.

        Args:
            *patterns: Patterns to check

        Returns:
            List of patterns that did not match
        """
        return [pattern for pattern in patterns if not self.has_acl(pattern)]

    def can_grant_acl(self, acl_pattern: str) -> bool:
        """Check if user can grant an ACL pattern to others.

        Users can only delegate permissions they themselves have.
        Negation patterns can always be granted (they restrict access).

        Args:
            acl_pattern: ACL pattern to potentially grant

        Returns:
            True if user can grant this ACL
        """
        return self._checker.may_add_access(acl_pattern)

    def can_revoke_acl(self, acl_pattern: str) -> bool:
        """Check if user can revoke an ACL pattern from others.

        Users can only revoke permissions they themselves have.

        Args:
            acl_pattern: ACL pattern to potentially revoke

        Returns:
            True if user can revoke this ACL
        """
        return self._checker.may_remove_access(acl_pattern)
