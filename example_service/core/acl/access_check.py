"""ACL pattern evaluation engine with caching.

This module provides the core pattern matching logic for ACL-based
authorization. It's designed to be:
- Fast: Heavy LRU caching at multiple levels
- Portable: No external dependencies (pure Python + regex)
- Flexible: Supports wildcards, negation, and reserved words

The pattern evaluation is performed locally - no network calls.
ACLs are obtained from the external auth service via token validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["AccessCheck", "ReservedWord", "get_cached_access_check"]


def get_cached_access_check(
    auth_id: str | None, session_id: str | None, acl: Iterable[str]
) -> AccessCheck:
    """Create a cached AccessCheck instance for ACL evaluation.

    This is the recommended way to create AccessCheck instances.
    Uses LRU caching for optimal performance on repeated checks.

    Args:
        auth_id: User authentication ID (for 'me' reserved word substitution)
        session_id: Session ID (for 'my_session' substitution)
        acl: List of ACL patterns the user has been granted

    Returns:
        Cached or newly created AccessCheck instance

    Example:
        >>> checker = get_cached_access_check(
        ...     "user-123",
        ...     "sess-456",
        ...     ["users.*.read", "users.me.update"]
        ... )
        >>> checker.matches_required_access("users.789.read")
        True
        >>> checker.matches_required_access("users.me.update")
        True  # 'me' matches 'user-123'
    """
    # Convert to tuple for hashability (required for LRU cache)
    acl_tuple = tuple(acl)
    return _get_cached_access_check(auth_id or "", session_id or "", acl_tuple)


@dataclass(frozen=True)
class ReservedWord:
    """Reserved word replacement used during ACL pattern matching.

    Reserved words allow context-aware ACL patterns:
    - 'me': Replaced with the current user's auth_id
    - 'my_session': Replaced with the current session_id
    - 'edit': Alias for 'update' (convenience)

    The replacement creates a regex alternation: (word|value)
    This allows patterns like "users.me.read" to match both
    "users.me.read" and "users.{actual_user_id}.read".
    """

    word: str
    value: str

    @property
    def replacement(self) -> str:
        """Get regex alternation pattern."""
        return f"({self.word}|{self.value})"

    def replace(self, candidate: str) -> str:
        """Replace word with alternation if it matches."""
        return self.replacement if candidate == self.word else candidate


@lru_cache(maxsize=2048)
def _substitute_reserved_words(
    expression: str, auth_id: str, session_id: str
) -> str:
    """Substitute reserved words in ACL pattern with actual values.

    Cached separately from regex compilation to maximize cache hits.
    Common patterns share the same substitution logic.

    Args:
        expression: Escaped ACL pattern (with wildcards already converted)
        auth_id: User authentication ID for 'me' substitution
        session_id: Session ID for 'my_session' substitution

    Returns:
        Pattern with reserved words substituted as regex alternations
    """
    pieces = expression.split("\\.")
    substitutions = (
        ReservedWord("me", auth_id),
        ReservedWord("my_session", session_id),
        ReservedWord("edit", "update"),
    )
    for reserved in substitutions:
        pieces = [reserved.replace(piece) for piece in pieces]
    return "\\.".join(pieces)


@lru_cache(maxsize=2048)
def _compile_acl_pattern(
    access: str, auth_id: str, session_id: str
) -> re.Pattern[str]:
    """Compile ACL pattern to regex with caching.

    This is performance-critical - compiles ACL patterns into regex.
    By caching with (pattern, auth_id, session_id) as key, we avoid
    recompiling on every request.

    Cache size of 2048 supports:
    - ~100-200 unique ACL patterns per user
    - ~10-20 concurrent users with unique credentials
    - Common patterns shared across users

    Args:
        access: Raw ACL pattern (e.g., 'users.*.read', 'me.profile.edit')
        auth_id: User authentication ID for reserved word substitution
        session_id: Session ID for reserved word substitution

    Returns:
        Compiled regex pattern ready for matching

    Pattern syntax:
        - '*' matches any single segment (non-greedy): [^.#]*?
        - '#' matches any number of segments (recursive): .*?
        - '.' is a literal segment separator
    """
    # Convert wildcards to regex patterns
    regex = re.escape(access).replace("\\*", "[^.#]*?").replace("\\#", ".*?")

    # Substitute reserved words with cached function
    regex = _substitute_reserved_words(regex, auth_id, session_id)

    # Compile and return the final pattern
    return re.compile(f"^{regex}$")


@lru_cache(maxsize=512)
def _get_cached_access_check(
    auth_id: str, session_id: str, acl_tuple: tuple[str, ...]
) -> AccessCheck:
    """Create and cache AccessCheck instances.

    Caches complete AccessCheck instances for maximum performance
    on repeated authorization checks with the same token.

    Cache size of 512 supports ~50-100 active tokens in high-traffic systems.

    Args:
        auth_id: User authentication ID
        session_id: Session ID
        acl_tuple: Tuple of ACL patterns (must be tuple for hashability)

    Returns:
        Cached or newly created AccessCheck instance
    """
    return AccessCheck(auth_id, session_id, acl_tuple)


class AccessCheck:
    """ACL pattern matcher with wildcard and negation support.

    Evaluates whether a required access pattern matches any of the
    user's granted ACL patterns, respecting negations.

    Pattern matching rules:
    1. Negation patterns (starting with '!') are checked first
    2. If any negation matches, access is DENIED
    3. If any positive pattern matches, access is GRANTED
    4. If nothing matches, access is DENIED

    Example:
        >>> checker = AccessCheck(
        ...     "user-123", "sess-456",
        ...     ["users.*.read", "!users.admin.*"]
        ... )
        >>> checker.matches_required_access("users.789.read")
        True  # Matches users.*.read
        >>> checker.matches_required_access("users.admin.read")
        False  # Blocked by !users.admin.*
    """

    def __init__(
        self, auth_id: str | None, session_id: str | None, acl: Iterable[str]
    ) -> None:
        """Initialize AccessCheck with cached pattern compilation.

        Args:
            auth_id: User authentication ID (used for 'me' reserved word)
            session_id: Session ID (used for 'my_session' reserved word)
            acl: List of ACL patterns, may include negations (prefixed with '!')
        """
        self.auth_id = auth_id or ""
        self.session_id = session_id or ""
        entries = list(acl)

        # Compile patterns using cached compilation
        self._positive = [
            _compile_acl_pattern(entry, self.auth_id, self.session_id)
            for entry in entries
            if not entry.startswith("!")
        ]
        self._negative = [
            _compile_acl_pattern(entry[1:], self.auth_id, self.session_id)
            for entry in entries
            if entry.startswith("!")
        ]

    def matches_required_access(self, required_access: str | None) -> bool:
        """Check if the required access matches any granted ACL.

        Args:
            required_access: The ACL pattern required for the operation.
                           If None, access is always granted.

        Returns:
            True if access should be granted, False otherwise.

        Matching logic:
            1. None required_access = always allowed
            2. Check negations first - any match = denied
            3. Check positives - any match = allowed
            4. No matches = denied
        """
        if required_access is None:
            return True

        # Check negations first - any match means denied
        for pattern in self._negative:
            if pattern.match(required_access):
                return False

        # Check positive patterns - any match means allowed
        return any(pattern.match(required_access) for pattern in self._positive)

    def may_add_access(self, new_access: str) -> bool:
        """Check if user can grant an ACL pattern to others.

        Users can only grant permissions they themselves have.
        Negation patterns can always be added (they restrict, not grant).

        Args:
            new_access: ACL pattern to potentially grant

        Returns:
            True if user can grant this ACL
        """
        return new_access.startswith("!") or self.matches_required_access(new_access)

    def may_remove_access(self, access_to_remove: str) -> bool:
        """Check if user can revoke an ACL pattern from others.

        Users can only revoke permissions they themselves have.

        Args:
            access_to_remove: ACL pattern to potentially revoke

        Returns:
            True if user can revoke this ACL
        """
        candidate = access_to_remove.removeprefix("!")
        return self.matches_required_access(candidate)
