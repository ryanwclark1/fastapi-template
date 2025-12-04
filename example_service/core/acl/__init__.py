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
    - AccessCheck: Pattern evaluation engine with wildcard and negation support
    - get_cached_access_check: Factory with LRU caching for performance
    - derive_permissions_from_acl: Convert ACL patterns to UI-friendly format
    - ACLChecker: Convenience wrapper for programmatic ACL checks

Pattern Syntax:
    - Dot-separated segments: "resource.identifier.action"
    - Single wildcard (*): matches one segment - "users.*.read"
    - Recursive wildcard (#): matches any depth - "admin.#"
    - Negation (!): denies access - "!users.admin.*"
    - Reserved words: "me" (current user), "my_session" (current session)

Examples:
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
from example_service.core.acl.derivation import (
    derive_permissions_from_acl,
    parse_acl_pattern,
)

__all__ = [
    "ACLChecker",
    "AccessCheck",
    "ReservedWord",
    "derive_permissions_from_acl",
    "get_cached_access_check",
    "parse_acl_pattern",
]
