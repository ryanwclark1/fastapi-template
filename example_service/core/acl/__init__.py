"""ACL (Access Control List) pattern evaluation for authorization.

This module provides ACL pattern matching that works with an external
authentication service (accent-auth). The pattern evaluation is performed
locally for performance, while token validation and ACL retrieval happen
via the external auth service.

Architecture:
    ┌─────────────────┐         ┌─────────────────┐
    │  accent-auth    │         │ example_service │
    │  (external)     │         │   (this app)    │
    │                 │         │                 │
    │  - Issue tokens │◄────────│  - Validate via │
    │  - Compute ACLs │         │    HTTP client  │
    │  - Introspect   │────────►│  - Check ACLs   │
    │                 │         │    locally      │
    └─────────────────┘         └─────────────────┘

Components:
    Pattern Evaluation:
        - AccessCheck: Pattern evaluation engine with wildcard and negation support
        - get_cached_access_check: Factory with LRU caching for performance
        - ACLChecker: Convenience wrapper for programmatic ACL checks

    Permission Constants:
        - ACLAction: Enum of standard actions (read, create, update, delete, etc.)
        - format_acl: Generate ACL strings consistently
        - parse_acl: Extract components from ACL strings
        - validate_acl_format: Validate ACL string format
        - get_resource_acls: Generate all standard ACLs for a resource
        - group_acls_by_resource: Group ACLs by resource for display

    UI Derivation (read-only):
        - derive_permissions_from_acl: Convert ACL patterns to UI-friendly format
        - parse_acl_pattern: Parse pattern into structured components

Pattern Syntax:
    - Dot-separated segments: "service.resource.action"
    - Single wildcard (*): matches one segment - "users.*.read"
    - Recursive wildcard (#): matches any depth - "admin.#"
    - Negation (!): denies access - "!users.admin.*"
    - Reserved words: "me" (current user), "my_session" (current session)

Defining Service-Specific ACL Permissions:
    Services should define their ACL permissions as class attributes for
    IDE autocompletion and typo prevention:

    >>> from example_service.core.acl import format_acl, ACLAction
    >>>
    >>> class UsersACL:
    ...     '''User management ACL permissions.'''
    ...     READ = format_acl("users", ACLAction.READ)
    ...     CREATE = format_acl("users", ACLAction.CREATE)
    ...     UPDATE = format_acl("users", ACLAction.UPDATE)
    ...     DELETE = format_acl("users", ACLAction.DELETE)
    ...     ADMIN = format_acl("users", ACLAction.ADMIN)
    ...     ALL = format_acl("users", ACLAction.ALL)
    >>>
    >>> # Use in routes:
    >>> @router.get("/users")
    >>> async def list_users(
    ...     user: Annotated[AuthUser, Depends(require_acl(UsersACL.READ))]
    ... ):
    ...     pass

Pattern Matching Examples:
    >>> from example_service.core.acl import get_cached_access_check
    >>>
    >>> # Create checker with user's ACLs (from token)
    >>> checker = get_cached_access_check(
    ...     auth_id="user-123",
    ...     session_id="sess-456",
    ...     acl=["users.*.read", "users.me.update", "!users.admin.*"]
    ... )
    >>>
    >>> # Check permissions
    >>> checker.matches_required_access("users.789.read")  # True
    >>> checker.matches_required_access("users.me.update")  # True (me = user-123)
    >>> checker.matches_required_access("users.admin.read")  # False (negated)
"""

from __future__ import annotations

from example_service.core.acl.access_check import (
    AccessCheck,
    ReservedWord,
    get_cached_access_check,
)
from example_service.core.acl.checker import ACLChecker
from example_service.core.acl.constants import (
    ACLAction,
    expand_wildcard_acls,
    format_acl,
    get_acl_prefix,
    get_resource_acls,
    group_acls_by_resource,
    parse_acl,
    validate_acl_format,
)
from example_service.core.acl.derivation import (
    derive_permissions_from_acl,
    parse_acl_pattern,
)

__all__ = [
    "ACLAction",
    "ACLChecker",
    "AccessCheck",
    "ReservedWord",
    "derive_permissions_from_acl",
    "expand_wildcard_acls",
    "format_acl",
    "get_acl_prefix",
    "get_cached_access_check",
    "get_resource_acls",
    "group_acls_by_resource",
    "parse_acl",
    "parse_acl_pattern",
    "validate_acl_format",
]
