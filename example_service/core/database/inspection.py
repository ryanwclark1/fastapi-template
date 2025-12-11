"""SQLAlchemy instance inspection utilities for change tracking.

These utilities use SQLAlchemy's inspection API to detect changes,
check loading state, and extract change details without triggering
database operations.

Complements the existing TimestampMixin and AuditColumnsMixin by detecting
*what* changed, not just *when*. Useful for:
- Conditional audit logging
- Change notifications/webhooks
- Optimistic concurrency
- N+1 query prevention

Example:
    >>> user = await session.get(User, 1)
    >>> user.name = "New Name"
    >>> if has_changes(user, "name"):
    ...     changes = get_changed_attributes(user)
    ...     audit_log = AuditLog(changes=changes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect as sa_inspect

if TYPE_CHECKING:
    from sqlalchemy.orm import InstanceState
    from sqlalchemy.orm.attributes import History


def has_changes(instance: Any, *attrs: str) -> bool:
    """Check if ORM instance has pending changes.

    Detects uncommitted modifications to the instance, optionally
    checking only specific attributes.

    Args:
        instance: SQLAlchemy ORM model instance
        *attrs: Optional attribute names to check. If empty, checks all.

    Returns:
        True if instance has pending changes, False otherwise.

    Example:
        >>> user = await session.get(User, 1)
        >>> has_changes(user)
        False
        >>> user.name = "New Name"
        >>> has_changes(user)
        True
        >>> has_changes(user, "email")  # Check specific attr
        False
        >>> has_changes(user, "name")
        True

    Note:
        - Works with pending (new), dirty (modified), and deleted instances
        - Does not trigger lazy loading
        - Respects SQLAlchemy's dirty tracking semantics
    """
    state: InstanceState[Any] = sa_inspect(instance)

    # Check if instance is pending (new) or deleted
    if state.pending or state.deleted:
        return True

    # If no specific attrs, check overall dirty state
    if not attrs:
        return state.modified

    # Check specific attributes
    for attr_name in attrs:
        if attr_name not in state.dict:
            continue

        attr_state = state.attrs.get(attr_name)
        if attr_state is None:
            continue

        history: History = attr_state.history
        if history.has_changes():
            return True

    return False


def is_loaded(instance: Any, attr: str) -> bool:
    """Check if relationship/attribute is loaded without triggering load.

    Useful for preventing N+1 queries in business logic by checking
    if related data is already available before accessing it.

    Args:
        instance: SQLAlchemy ORM model instance
        attr: Attribute name to check

    Returns:
        True if attribute is loaded, False if would trigger lazy load.

    Example:
        >>> user = await session.get(User, 1)  # No eager loading
        >>> is_loaded(user, "posts")
        False
        >>> user = await session.get(User, 1, options=[selectinload(User.posts)])
        >>> is_loaded(user, "posts")
        True
        >>> if is_loaded(user, "posts"):
        ...     # Safe to access without DB query
        ...     print(f"User has {len(user.posts)} posts")

    Note:
        - Does NOT trigger lazy loading (unlike direct attribute access)
        - Works for relationships, deferred columns, and regular columns
        - Returns True for scalar columns that are always loaded
    """
    state: InstanceState[Any] = sa_inspect(instance)

    # Check if attribute is in instance dict (loaded)
    if attr in state.dict:
        return True

    # Check unloaded collection
    if attr in state.unloaded:
        return False

    # Check if it's an expired attribute
    if state.expired:
        return False

    # Check attribute state for relationships
    attr_state = state.attrs.get(attr)
    if attr_state is None:
        return False

    return attr_state.loaded_value is not None


def get_changed_attributes(instance: Any) -> dict[str, tuple[Any, Any]]:
    """Get dictionary of changed attributes with old and new values.

    Returns all modified attributes with their previous and current values.
    Useful for audit logging, webhooks, and change notifications.

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        Dictionary mapping attribute names to (old_value, new_value) tuples.
        Empty dict if no changes.

    Example:
        >>> user = await session.get(User, 1)
        >>> user.name = "New Name"
        >>> user.email = "new@example.com"
        >>> changes = get_changed_attributes(user)
        >>> changes
        {'name': ('Old Name', 'New Name'), 'email': ('old@ex.com', 'new@example.com')}

        # Integration with audit logging
        >>> if changes:
        ...     audit_log = AuditLog(
        ...         entity_type="user",
        ...         entity_id=str(user.id),
        ...         changes={k: {"old": v[0], "new": v[1]} for k, v in changes.items()},
        ...     )

    Note:
        - Only includes actually modified attributes
        - Handles None values correctly
        - Does not include relationship changes (only column attributes)
    """
    state: InstanceState[Any] = sa_inspect(instance)
    changes: dict[str, tuple[Any, Any]] = {}

    mapper = state.mapper

    for attr in mapper.column_attrs:
        attr_name = attr.key
        attr_state = state.attrs.get(attr_name)

        if attr_state is None:
            continue

        history: History = attr_state.history

        if history.has_changes():
            old_value = history.deleted[0] if history.deleted else None
            new_value = history.added[0] if history.added else None
            changes[attr_name] = (old_value, new_value)

    return changes


def get_original_values(instance: Any, *attrs: str) -> dict[str, Any]:
    """Get original values of attributes before modification.

    Useful for comparison or reverting changes.

    Args:
        instance: SQLAlchemy ORM model instance
        *attrs: Attribute names to get. If empty, gets all changed.

    Returns:
        Dictionary of attribute names to their original values.

    Example:
        >>> user.name = "New Name"
        >>> get_original_values(user, "name")
        {'name': 'Old Name'}
        >>> get_original_values(user)  # All changed attrs
        {'name': 'Old Name'}
    """
    state: InstanceState[Any] = sa_inspect(instance)
    original: dict[str, Any] = {}

    attrs_to_check: tuple[str, ...] | list[str]
    attrs_to_check = attrs or [a.key for a in state.mapper.column_attrs]

    for attr_name in attrs_to_check:
        attr_state = state.attrs.get(attr_name)
        if attr_state is None:
            continue

        history: History = attr_state.history

        if history.deleted:
            original[attr_name] = history.deleted[0]
        elif attr_name in state.dict:
            # Not changed, return current value
            original[attr_name] = state.dict[attr_name]

    return original


def get_instance_state(instance: Any) -> str:
    """Get human-readable state of instance.

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        One of: "transient", "pending", "persistent", "detached", "deleted"

    Example:
        >>> user = User(name="New")
        >>> get_instance_state(user)
        'transient'
        >>> session.add(user)
        >>> get_instance_state(user)
        'pending'
        >>> await session.flush()
        >>> get_instance_state(user)
        'persistent'
    """
    state: InstanceState[Any] = sa_inspect(instance)

    if state.transient:
        return "transient"
    if state.pending:
        return "pending"
    if state.deleted:
        return "deleted"
    if state.detached:
        return "detached"
    return "persistent"


def is_new(instance: Any) -> bool:
    """Check if instance is new (not yet in database).

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        True if instance has never been flushed to database
    """
    state: InstanceState[Any] = sa_inspect(instance)
    return state.pending or state.transient


def is_modified(instance: Any) -> bool:
    """Check if instance has any modifications.

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        True if instance has uncommitted changes
    """
    state: InstanceState[Any] = sa_inspect(instance)
    return state.modified


def is_deleted(instance: Any) -> bool:
    """Check if instance is marked for deletion.

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        True if instance will be deleted on commit
    """
    state: InstanceState[Any] = sa_inspect(instance)
    return state.deleted


def is_persistent(instance: Any) -> bool:
    """Check if instance is persistent (in database, attached to session).

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        True if instance exists in database and is attached to session
    """
    state: InstanceState[Any] = sa_inspect(instance)
    return state.persistent


def is_detached(instance: Any) -> bool:
    """Check if instance is detached (was in database but no longer in session).

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        True if instance was previously persistent but is now detached
    """
    state: InstanceState[Any] = sa_inspect(instance)
    return state.detached


def get_primary_key(instance: Any) -> tuple[Any, ...]:
    """Get primary key value(s) for instance.

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        Tuple of primary key values (single value tuple for simple PKs)

    Example:
        >>> get_primary_key(user)
        (1,)
        >>> get_primary_key(composite_pk_model)
        (1, 'abc')
    """
    state: InstanceState[Any] = sa_inspect(instance)
    mapper = state.mapper

    return tuple(
        mapper.primary_key_from_instance(instance),
    )


def get_identity_key(instance: Any) -> tuple[type, tuple[Any, ...]] | None:
    """Get identity key for instance (used by session identity map).

    Args:
        instance: SQLAlchemy ORM model instance

    Returns:
        Tuple of (model_class, primary_key_tuple) or None if not persistent

    Example:
        >>> get_identity_key(user)
        (<class 'User'>, (1,))
    """
    state: InstanceState[Any] = sa_inspect(instance)

    if state.key is None:
        return None

    return (state.key[0], state.key[1])


__all__ = [
    "get_changed_attributes",
    "get_identity_key",
    "get_instance_state",
    "get_original_values",
    "get_primary_key",
    "has_changes",
    "is_deleted",
    "is_detached",
    "is_loaded",
    "is_modified",
    "is_new",
    "is_persistent",
]
