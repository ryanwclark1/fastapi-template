"""Utilities for handling partial updates with change tracking.

This module provides generic utilities for applying partial updates to
entities while tracking what changed. This is useful for:
- Audit logging (knowing exactly what changed)
- Event publishing (including change details)
- Reducing boilerplate in update endpoints

Example:
    from example_service.utils.updates import apply_updates

    @router.patch("/items/{item_id}")
    async def update_item(
        item_id: UUID,
        payload: ItemUpdate,
        session: DbSessionDep,
    ) -> ItemResponse:
        item = await get_item(session, item_id)

        result = apply_updates(
            item,
            payload,
            fields=["name", "description", "status"],
            transform={"updated_at": lambda dt: dt.isoformat()},
        )

        if result.applied:
            logger.info("Item updated", extra={"changes": result.changes})

        await session.commit()
        return ItemResponse.from_model(item)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class UpdateResult:
    """Result of applying updates to an entity.

    Attributes:
        applied: True if any changes were made.
        changes: Dictionary of field names to new values (for logging/events).
    """

    applied: bool = False
    changes: dict[str, Any] = field(default_factory=dict)


def apply_updates(
    entity: Any,
    payload: Mapping[str, Any] | Any,
    *,
    fields: list[str] | None = None,
    exclude: set[str] | None = None,
    track_changes: bool = True,
    transform: dict[str, Callable[[Any], Any]] | None = None,
    skip_none: bool = True,
) -> UpdateResult:
    """Apply partial updates from payload to entity with change tracking.

    This function handles the common pattern of:
    1. Checking if a field was provided in the payload
    2. Checking if it's different from the current value
    3. Updating the entity
    4. Tracking what changed for audit/events

    Args:
        entity: Target entity (SQLAlchemy model, dataclass, etc.) to update.
        payload: Update payload - can be a dict, Pydantic model, or any object
            with attributes. If Pydantic, uses model_dump(exclude_unset=True).
        fields: Specific fields to update. If None, updates all non-None fields
            in the payload (excluding those in `exclude`).
        exclude: Fields to exclude from updates (e.g., {"id", "created_at"}).
        track_changes: Whether to track changes in the result. Set False for
            simple updates where you don't need the change log.
        transform: Dictionary mapping field names to transform functions.
            Transforms are applied to the change log value, not the entity.
            Useful for converting datetimes to ISO format for JSON serialization.
        skip_none: If True (default), None values in payload are skipped.
            Set False to allow explicitly setting fields to None.

    Returns:
        UpdateResult with:
            - applied: True if any changes were made
            - changes: Dict of {field_name: new_value} for changed fields

    Example:
        # Simple update
        result = apply_updates(reminder, payload)

        # With specific fields and transforms
        result = apply_updates(
            reminder,
            payload,
            fields=["title", "description", "remind_at"],
            transform={
                "remind_at": lambda dt: dt.isoformat() if dt else None,
            },
        )

        # Check and log changes
        if result.applied:
            logger.info(f"Updated {len(result.changes)} fields")
            await publish_event(ReminderUpdatedEvent(changes=result.changes))
    """
    exclude = exclude or set()
    transform = transform or {}
    changes: dict[str, Any] = {}

    # Get payload as dict if it's a Pydantic model
    if hasattr(payload, "model_dump"):
        # Pydantic v2 - only include fields that were explicitly set
        payload_dict = payload.model_dump(exclude_unset=True)
    elif hasattr(payload, "dict"):
        # Pydantic v1 fallback
        payload_dict = payload.dict(exclude_unset=True)
    elif isinstance(payload, Mapping):
        payload_dict = dict(payload)
    else:
        # Assume it's an object with attributes
        payload_dict = {
            k: v for k, v in vars(payload).items() if not k.startswith("_")
        }

    # Determine fields to process
    if fields is None:
        fields_to_update = [k for k in payload_dict if k not in exclude]
    else:
        fields_to_update = [f for f in fields if f not in exclude]

    for field_name in fields_to_update:
        if field_name not in payload_dict:
            continue

        new_value = payload_dict[field_name]

        # Skip None values unless explicitly allowed
        if skip_none and new_value is None:
            continue

        current_value = getattr(entity, field_name, None)

        # Only update if value changed
        if current_value != new_value:
            setattr(entity, field_name, new_value)

            if track_changes:
                # Apply transform for change log if provided
                if field_name in transform:
                    changes[field_name] = transform[field_name](new_value)
                else:
                    changes[field_name] = new_value

    return UpdateResult(applied=bool(changes), changes=changes)


def apply_update_if_changed(
    entity: Any,
    field_name: str,
    new_value: Any,
    *,
    changes: dict[str, Any] | None = None,
    transform: Callable[[Any], Any] | None = None,
) -> bool:
    """Apply a single field update if the value changed.

    Simpler alternative to apply_updates for cases where you need
    custom logic between field updates.

    Args:
        entity: Target entity to update.
        field_name: Name of the field to update.
        new_value: New value for the field.
        changes: Optional dict to record the change (mutated in place).
        transform: Optional function to transform value for change log.

    Returns:
        True if the field was updated, False otherwise.

    Example:
        changes = {}

        if apply_update_if_changed(reminder, "title", payload.title, changes=changes):
            logger.debug("Title changed")

        if apply_update_if_changed(
            reminder,
            "remind_at",
            payload.remind_at,
            changes=changes,
            transform=lambda dt: dt.isoformat() if dt else None,
        ):
            logger.debug("Remind at changed")
    """
    current_value = getattr(entity, field_name, None)

    if current_value != new_value:
        setattr(entity, field_name, new_value)

        if changes is not None:
            if transform:
                changes[field_name] = transform(new_value)
            else:
                changes[field_name] = new_value

        return True

    return False
