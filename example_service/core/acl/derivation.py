"""ACL pattern derivation utilities for UI display.

This module provides utilities for converting ACL patterns into
human-readable resource/action permissions for frontend/UI display.

WARNING: These derived permissions are READ-ONLY metadata.
NEVER use them for authorization decisions!

All authorization must use ACL patterns via:
- require_acl() dependency for route protection
- AccessCheck.matches_required_access() for programmatic checks

The derivation logic is intentionally lossy and cannot represent
the full expressiveness of ACL patterns (negations, nested wildcards,
reserved word semantics, precedence rules).
"""

from __future__ import annotations

__all__ = ["derive_permissions_from_acl", "parse_acl_pattern"]


def parse_acl_pattern(pattern: str) -> dict[str, str | bool | list[str]]:
    """Parse ACL pattern into structured components for display.

    Args:
        pattern: ACL pattern (e.g., "users.*.read", "!users.admin.*")

    Returns:
        Dictionary with:
            - negation: Whether pattern starts with "!" (denial)
            - parts: List of pattern parts split by "."
            - resource: First part (resource name)
            - action: Last part (action name, or "all" for wildcards)
            - scope: Derived scope ("self", "all", "except_X", etc.)
            - raw: Original pattern without negation prefix

    Example:
        >>> parse_acl_pattern("users.me.read")
        {
            "negation": False,
            "parts": ["users", "me", "read"],
            "resource": "users",
            "action": "read",
            "scope": "self",
            "raw": "users.me.read"
        }

        >>> parse_acl_pattern("!users.admin.*")
        {
            "negation": True,
            "parts": ["users", "admin", "*"],
            "resource": "users",
            "action": "all",
            "scope": "except_admin",
            "raw": "users.admin.*"
        }
    """
    # Check for negation
    negation = pattern.startswith("!")
    raw_pattern = pattern.lstrip("!")

    # Split into parts
    parts = raw_pattern.split(".")

    if not parts:
        return {
            "negation": negation,
            "parts": [],
            "resource": "",
            "action": "",
            "scope": "",
            "raw": raw_pattern,
        }

    # Extract resource (first part)
    resource = parts[0]

    # Extract action (last part, handle wildcards)
    last_part = parts[-1] if parts else ""
    if last_part == "*":
        action = "all"
    elif last_part == "#":
        action = "all_recursive"
    else:
        action = last_part

    # Determine scope based on pattern structure
    scope = _derive_scope(parts, negation)

    return {
        "negation": negation,
        "parts": parts,
        "resource": resource,
        "action": action,
        "scope": scope,
        "raw": raw_pattern,
    }


def _derive_scope(parts: list[str], is_negation: bool) -> str:
    """Derive permission scope from pattern parts.

    Args:
        parts: Pattern parts (e.g., ["users", "me", "read"])
        is_negation: Whether this is a negation pattern

    Returns:
        Scope string:
            - "self": Pattern contains "me"
            - "own_session": Pattern contains "my_session"
            - "all": Pattern uses "*" wildcard
            - "all_recursive": Pattern uses "#" wildcard
            - "except_{target}": Negation pattern
            - "specific": Specific resource identifier
            - "unknown": Cannot determine scope
    """
    # Check for reserved words
    if "me" in parts:
        return "self"
    if "my_session" in parts:
        return "own_session"

    # Check for wildcards
    if "#" in parts:
        return "all_recursive"
    if "*" in parts:
        return "all"

    # Negation patterns
    if is_negation and len(parts) >= 2:
        # e.g., !users.admin.* → except_admin
        target = parts[1]
        return f"except_{target}"

    # Specific resource (e.g., users.123.read)
    if len(parts) >= 2 and parts[1] not in ("*", "#", "me", "my_session"):
        return "specific"

    return "unknown"


def derive_permissions_from_acl(acl_patterns: list[str]) -> list[dict[str, str]]:
    """Derive resource/action permissions from ACL patterns for UI display.

    WARNING: This conversion is LOSSY. It cannot fully represent:
        - Complex negations (e.g., "!users.admin.*" excludes admin users)
        - Nested wildcards (e.g., "users.*.groups.*.read")
        - Reserved word semantics (e.g., "me" vs specific user ID)
        - ACL precedence rules (negations override positives)

    DO NOT use derived permissions for authorization checks!
    Use require_acl() or AccessCheck.matches_required_access() instead.

    Args:
        acl_patterns: List of ACL patterns

    Returns:
        List of dicts with keys:
            - resource: Resource name
            - action: Action name
            - scope: Permission scope
            - pattern: Original ACL pattern

    Example:
        >>> derive_permissions_from_acl([
        ...     "users.me.read",
        ...     "users.*.update",
        ...     "!users.admin.*",
        ...     "calls.#",
        ... ])
        [
            {"resource": "users", "action": "read", "scope": "self", "pattern": "users.me.read"},
            {"resource": "users", "action": "update", "scope": "all", "pattern": "users.*.update"},
            {"resource": "users", "action": "all", "scope": "except_admin", "pattern": "!users.admin.*"},
            {"resource": "calls", "action": "all_recursive", "scope": "all_recursive", "pattern": "calls.#"},
        ]
    """
    permissions: list[dict[str, str]] = []

    for pattern in acl_patterns:
        parsed = parse_acl_pattern(pattern)

        # Skip empty/invalid patterns
        if not parsed["resource"]:
            continue

        permissions.append({
            "resource": str(parsed["resource"]),
            "action": str(parsed["action"]),
            "scope": str(parsed["scope"]),
            "pattern": pattern,
        })

    return permissions
