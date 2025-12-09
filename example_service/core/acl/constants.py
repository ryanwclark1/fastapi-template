"""ACL permission constants and utilities.

This module provides utilities for defining service-specific ACL permissions
using the dot-notation format: {service}.{resource}.{action}

Components:
    - ACLAction: Standard action names (read, create, update, delete, etc.)
    - format_acl: Generate ACL strings consistently
    - parse_acl: Extract components from ACL strings
    - validate_acl_format: Validate ACL string format
    - get_resource_acls: Generate all standard ACLs for a resource

Usage:
    Services should define their ACL permissions as class attributes:

    >>> from example_service.core.acl.constants import format_acl
    >>>
    >>> class UsersACL:
    ...     READ = format_acl("users", "read")
    ...     CREATE = format_acl("users", "create")
    ...     UPDATE = format_acl("users", "update")
    ...     DELETE = format_acl("users", "delete")
    ...     ADMIN = format_acl("users", "admin")
    ...     ALL = format_acl("users", "*")
    >>>
    >>> # Use in routes:
    >>> @router.get("/users")
    >>> async def list_users(
    ...     user: Annotated[AuthUser, Depends(require_acl(UsersACL.READ))]
    ... ):
    ...     pass

Pattern Syntax:
    - Dot-separated segments: "service.resource.action"
    - Single wildcard (*): matches one segment
    - Recursive wildcard (#): matches any depth
    - Negation (!): prefix for explicit deny

Examples:
    >>> format_acl("calls", "read")
    'example_service.calls.read'

    >>> parse_acl("example_service.calls.read")
    {'service': 'example_service', 'resource': 'calls', 'action': 'read'}

    >>> validate_acl_format("example_service.calls.read")
    True
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from example_service.core.settings import get_app_settings

# Minimum number of segments in a valid ACL: service.resource.action
_MIN_ACL_SEGMENTS = 3

__all__ = [
    "ACLAction",
    "format_acl",
    "get_acl_prefix",
    "get_resource_acls",
    "parse_acl",
    "validate_acl_format",
]


# =============================================================================
# ACL Prefix Configuration
# =============================================================================


@lru_cache(maxsize=1)
def get_acl_prefix() -> str:
    """Get the ACL prefix for this service.

    The prefix is derived from the service_name in settings,
    converted to lowercase with hyphens replaced by underscores.

    Returns:
        ACL prefix string (e.g., "example_service")

    Example:
        >>> get_acl_prefix()
        'example_service'
    """
    settings = get_app_settings()
    # Convert service name to ACL-safe format: lowercase, hyphens to underscores
    return settings.service_name.lower().replace("-", "_").replace(" ", "_")


# =============================================================================
# Standard ACL Actions
# =============================================================================


class ACLAction(str, Enum):
    """Standard ACL action names.

    These are the common actions used across resources. Services may
    define additional custom actions as needed.

    Standard CRUD actions:
        - READ: View/list resources
        - CREATE: Create new resources
        - UPDATE: Modify existing resources
        - DELETE: Remove resources

    Extended actions:
        - EXECUTE: Trigger operations (jobs, workflows, etc.)
        - ADMIN: Full administrative access to resource
        - EXPORT: Export/download data
        - IMPORT: Import/upload data

    Wildcards:
        - ALL: Single-level wildcard (*)
        - RECURSIVE: Multi-level wildcard (#)
    """

    # Standard CRUD
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

    # Extended actions
    EXECUTE = "execute"
    ADMIN = "admin"
    EXPORT = "export"
    IMPORT = "import"

    # Wildcards (for use in ACL patterns)
    ALL = "*"
    RECURSIVE = "#"


# =============================================================================
# ACL Formatting Utilities
# =============================================================================


def format_acl(
    resource: str,
    action: str | ACLAction,
    *,
    service: str | None = None,
) -> str:
    """Format an ACL permission string.

    Generates a standardized ACL string in the format:
    `{service}.{resource}.{action}`

    Args:
        resource: Resource name (e.g., "users", "calls", "recordings")
        action: Action name (e.g., "read", ACLAction.READ, "*")
        service: Service prefix (defaults to app name from settings)

    Returns:
        Formatted ACL string

    Examples:
        >>> format_acl("users", "read")
        'example_service.users.read'

        >>> format_acl("users", ACLAction.READ)
        'example_service.users.read'

        >>> format_acl("calls", "*")
        'example_service.calls.*'

        >>> format_acl("users", "read", service="custom_service")
        'custom_service.users.read'
    """
    prefix = service if service is not None else get_acl_prefix()
    action_str = action.value if isinstance(action, ACLAction) else action
    return f"{prefix}.{resource}.{action_str}"


def parse_acl(acl: str) -> dict[str, str | bool]:
    """Parse an ACL permission string into components.

    Extracts the service, resource, and action from a dot-notation ACL string.
    Handles negation prefix and complex patterns gracefully.

    Args:
        acl: ACL string (e.g., "example_service.users.read")

    Returns:
        Dictionary with keys:
            - service: Service name (first segment)
            - resource: Resource name (middle segments joined)
            - action: Action name (last segment)
            - negation: Whether pattern is negated (starts with !)
            - raw: Original pattern without negation

    Examples:
        >>> parse_acl("example_service.users.read")
        {'service': 'example_service', 'resource': 'users', 'action': 'read',
         'negation': False, 'raw': 'example_service.users.read'}

        >>> parse_acl("!example_service.admin.*")
        {'service': 'example_service', 'resource': 'admin', 'action': '*',
         'negation': True, 'raw': 'example_service.admin.*'}

        >>> parse_acl("service.nested.resource.read")
        {'service': 'service', 'resource': 'nested.resource', 'action': 'read',
         'negation': False, 'raw': 'service.nested.resource.read'}
    """
    # Handle negation
    negation = acl.startswith("!")
    raw = acl.lstrip("!")

    parts = raw.split(".")

    if len(parts) < _MIN_ACL_SEGMENTS:
        # Invalid or incomplete pattern
        return {
            "service": parts[0] if len(parts) > 0 else "",
            "resource": parts[1] if len(parts) > 1 else "",
            "action": "",
            "negation": negation,
            "raw": raw,
        }

    return {
        "service": parts[0],
        "resource": ".".join(parts[1:-1]),  # Support nested resources
        "action": parts[-1],
        "negation": negation,
        "raw": raw,
    }


def validate_acl_format(acl: str) -> bool:
    """Validate ACL permission string format.

    Checks that the ACL string follows the expected format:
    - At least 3 dot-separated segments (service.resource.action)
    - All segments are non-empty
    - Wildcards (* and #) are allowed
    - Negation prefix (!) is allowed

    Args:
        acl: ACL string to validate

    Returns:
        True if format is valid, False otherwise

    Examples:
        >>> validate_acl_format("example_service.users.read")
        True

        >>> validate_acl_format("example_service.users.*")
        True

        >>> validate_acl_format("!example_service.admin.#")
        True

        >>> validate_acl_format("invalid")
        False

        >>> validate_acl_format("service.resource")
        False
    """
    # Handle negation prefix
    check_acl = acl.lstrip("!")

    # Empty after removing negation
    if not check_acl:
        return False

    parts = check_acl.split(".")

    # Must have at least service.resource.action
    if len(parts) < _MIN_ACL_SEGMENTS:
        return False

    # All parts must be non-empty (allow wildcards)
    return all(part.strip() for part in parts)


def get_resource_acls(
    resource: str,
    actions: list[str | ACLAction] | None = None,
    *,
    service: str | None = None,
    include_wildcard: bool = True,
) -> list[str]:
    """Generate all ACL permissions for a resource.

    Creates a list of ACL strings for common actions on a resource.
    Useful for bulk permission assignment or documentation.

    Args:
        resource: Resource name (e.g., "users", "calls")
        actions: Specific actions to include (default: standard CRUD + admin)
        service: Service prefix (defaults to app name)
        include_wildcard: Whether to include the wildcard permission

    Returns:
        List of ACL permission strings

    Examples:
        >>> get_resource_acls("users")
        ['example_service.users.read', 'example_service.users.create',
         'example_service.users.update', 'example_service.users.delete',
         'example_service.users.admin', 'example_service.users.*']

        >>> get_resource_acls("calls", actions=["read", "create"])
        ['example_service.calls.read', 'example_service.calls.create']

        >>> get_resource_acls("users", include_wildcard=False)
        ['example_service.users.read', 'example_service.users.create',
         'example_service.users.update', 'example_service.users.delete',
         'example_service.users.admin']
    """
    if actions is None:
        actions = [
            ACLAction.READ,
            ACLAction.CREATE,
            ACLAction.UPDATE,
            ACLAction.DELETE,
            ACLAction.ADMIN,
        ]

    acls = [format_acl(resource, action, service=service) for action in actions]

    if include_wildcard:
        acls.append(format_acl(resource, ACLAction.ALL, service=service))

    return acls


# =============================================================================
# ACL Grouping Utilities
# =============================================================================


def group_acls_by_resource(
    acl_patterns: list[str],
) -> dict[str, list[str]]:
    """Group ACL patterns by resource for display purposes.

    Parses ACL patterns and groups them by their resource component,
    collecting the actions for each resource.

    WARNING: This is for display/UI purposes only. Do not use for
    authorization decisions - use the pattern matching engine instead.

    Args:
        acl_patterns: List of ACL patterns

    Returns:
        Dictionary mapping resource names to lists of actions

    Example:
        >>> group_acls_by_resource([
        ...     "service.users.read",
        ...     "service.users.create",
        ...     "service.calls.read",
        ...     "service.calls.*",
        ... ])
        {
            'users': ['read', 'create'],
            'calls': ['read', '*']
        }
    """
    grouped: dict[str, list[str]] = {}

    for pattern in acl_patterns:
        # Skip negation patterns for grouping (they're denials)
        if pattern.startswith("!"):
            continue

        parsed = parse_acl(pattern)
        resource = str(parsed["resource"])
        action = str(parsed["action"])

        if resource and action:
            if resource not in grouped:
                grouped[resource] = []
            if action not in grouped[resource]:
                grouped[resource].append(action)

    return grouped


def expand_wildcard_acls(
    acl_patterns: list[str],
    known_resources: list[str] | None = None,
) -> list[str]:
    """Expand wildcard ACLs into explicit permissions for display.

    Takes ACL patterns that may contain wildcards and expands them
    into explicit permission strings. Useful for showing users what
    permissions a wildcard grants.

    WARNING: This is for display/UI purposes only. The actual pattern
    matching engine handles wildcards directly.

    Args:
        acl_patterns: List of ACL patterns (may contain wildcards)
        known_resources: List of known resource names for expansion

    Returns:
        List of expanded ACL strings (wildcards replaced where possible)

    Example:
        >>> expand_wildcard_acls(
        ...     ["service.users.*"],
        ...     known_resources=["users"]
        ... )
        ['service.users.read', 'service.users.create',
         'service.users.update', 'service.users.delete', 'service.users.admin']
    """
    if known_resources is None:
        known_resources = []

    expanded: list[str] = []
    standard_actions = ["read", "create", "update", "delete", "admin"]

    for pattern in acl_patterns:
        parsed = parse_acl(pattern)
        resource = str(parsed["resource"])
        service = str(parsed["service"])

        # If action is wildcard, expand to standard actions
        if parsed["action"] == "*" and resource:
            expanded.extend(
                format_acl(resource, action, service=service)
                for action in standard_actions
            )
        elif parsed["action"] == "#":
            # Recursive wildcard - just note it grants everything
            expanded.append(pattern)
        else:
            # Not a wildcard, keep as-is
            expanded.append(pattern)

    return expanded
