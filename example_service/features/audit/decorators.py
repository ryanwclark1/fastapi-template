"""Audit logging decorators.

Provides decorators for automatic audit logging of service methods.
"""

from __future__ import annotations

from functools import wraps
import logging
import time
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from .models import AuditAction

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def audited(
    entity_type: str,
    action: AuditAction | None = None,
    capture_result: bool = True,
    capture_args: bool = False,
    include_duration: bool = True,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator to automatically log audit entries for service methods.

    This decorator wraps async service methods and automatically creates
    audit log entries based on the method execution.

    Args:
        entity_type: Type of entity being operated on.
        action: Override action type (auto-detected from method name if not provided).
        capture_result: Whether to capture the result in new_values.
        capture_args: Whether to capture arguments in metadata.
        include_duration: Whether to track operation duration.

    Returns:
        Decorated function that logs audit entries.

    Example:
        class ReminderService:
            @audited("reminder", action=AuditAction.CREATE)
            async def create(self, data: ReminderCreate) -> Reminder:
                ...

            @audited("reminder")  # Action auto-detected as UPDATE
            async def update(self, id: str, data: ReminderUpdate) -> Reminder:
                ...
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            from fastapi import Request

            from example_service.infra.database.session import get_async_session

            from .service import AuditService

            # Determine action from method name if not provided
            detected_action = action
            if detected_action is None:
                method_name = func.__name__.lower()
                if "create" in method_name or "add" in method_name:
                    detected_action = AuditAction.CREATE
                elif "update" in method_name or "edit" in method_name:
                    detected_action = AuditAction.UPDATE
                elif "delete" in method_name or "remove" in method_name:
                    detected_action = AuditAction.DELETE
                elif "get" in method_name or "read" in method_name or "list" in method_name:
                    detected_action = AuditAction.READ
                else:
                    detected_action = AuditAction.READ

            # Extract context from args/kwargs
            request: Request | None = None
            user_id: str | None = None
            actor_roles: list[str] = []
            tenant_id: str | None = None
            entity_id: str | None = None

            # Try to find request object in args
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # Check kwargs for common patterns
            if "request" in kwargs and isinstance(kwargs["request"], Request):
                request = kwargs["request"]

            # Extract user/tenant/roles from request state
            if request:
                user_id = getattr(request.state, "user_id", None)
                if user_id is None:
                    user = getattr(request.state, "user", None)
                    if user:
                        user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
                        # Extract roles from user object
                        user_roles = getattr(user, "roles", None)
                        if user_roles:
                            actor_roles = list(user_roles) if not isinstance(user_roles, list) else user_roles
                tenant_id = getattr(request.state, "tenant_uuid", None)
                # Also check for roles directly on request state
                if not actor_roles:
                    state_roles = getattr(request.state, "roles", None)
                    if state_roles:
                        actor_roles = list(state_roles) if not isinstance(state_roles, list) else state_roles

            # Try to extract entity_id from kwargs
            entity_id = kwargs.get("id") or kwargs.get("entity_id") # type: ignore
            if entity_id is not None:
                entity_id = str(entity_id)

            # Build metadata
            metadata: dict[str, Any] = {
                "function": func.__name__,
                "module": func.__module__,
            }
            if capture_args:
                # Capture safe arguments (exclude sensitive data)
                safe_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k not in ("password", "token", "secret", "key", "request")
                    and not isinstance(v, Request)
                }
                metadata["args"] = safe_kwargs

            # Track timing
            start_time = time.monotonic() if include_duration else None
            success = True
            error_message: str | None = None
            result: R | None = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                # Calculate duration
                duration_ms: int | None = None
                if start_time is not None:
                    duration_ms = int((time.monotonic() - start_time) * 1000)

                # Build new_values from result
                new_values: dict[str, Any] | None = None
                if capture_result and result is not None:
                    if hasattr(result, "model_dump"):
                        new_values = result.model_dump()
                    elif hasattr(result, "__dict__"):
                        new_values = {
                            k: v
                            for k, v in result.__dict__.items()
                            if not k.startswith("_")
                        }

                    # Extract entity_id from result if not already set
                    if entity_id is None and new_values:
                        entity_id = str(new_values.get("id", ""))

                # Log the audit entry
                try:
                    async with get_async_session() as session:
                        audit_service = AuditService(session)
                        await audit_service.log(
                            action=detected_action,
                            entity_type=entity_type,
                            entity_id=entity_id,
                            user_id=user_id,
                            actor_roles=actor_roles,
                            tenant_id=tenant_id,
                            new_values=new_values,
                            ip_address=request.client.host if request and request.client else None,
                            user_agent=request.headers.get("user-agent") if request else None,
                            request_id=getattr(request.state, "request_id", None) if request else None,
                            endpoint=str(request.url.path) if request else None,
                            method=request.method if request else None,
                            metadata=metadata,
                            success=success,
                            error_message=error_message,
                            duration_ms=duration_ms,
                        )
                except Exception as audit_error:
                    # Don't fail the main operation if audit logging fails
                    logger.warning(
                        f"Failed to create audit log: {audit_error}",
                        extra={"entity_type": entity_type, "action": detected_action},
                    )

        return wrapper

    return decorator


def audit_action(
    action: AuditAction,
    entity_type: str,
    entity_id_param: str = "id",
    old_values_param: str | None = None,
    new_values_param: str | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator for explicit audit action logging.

    More explicit version of @audited that gives fine-grained control
    over what gets logged.

    Args:
        action: The audit action to log.
        entity_type: Type of entity.
        entity_id_param: Name of parameter containing entity ID.
        old_values_param: Name of parameter containing old values.
        new_values_param: Name of parameter containing new values.

    Returns:
        Decorated function.

    Example:
        @audit_action(
            action=AuditAction.UPDATE,
            entity_type="reminder",
            entity_id_param="reminder_id",
            old_values_param="old_data",
            new_values_param="new_data",
        )
        async def update_reminder(
            reminder_id: str,
            old_data: dict,
            new_data: dict,
        ) -> Reminder:
            ...
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:

            from example_service.infra.database.session import get_async_session

            from .service import AuditService

            # Extract values from kwargs
            entity_id = kwargs.get(entity_id_param)
            if entity_id is not None:
                entity_id = str(entity_id)

            old_values = kwargs.get(old_values_param) if old_values_param else None
            new_values = kwargs.get(new_values_param) if new_values_param else None

            # Extract request context
            request: Request | None = kwargs.get("request") # type: ignore
            user_id: str | None = None
            actor_roles: list[str] = []
            tenant_id: str | None = None

            if request:
                user = getattr(request.state, "user", None)
                if user:
                    user_id = getattr(user, "user_id", None)
                    # Extract roles from user object
                    user_roles = getattr(user, "roles", None)
                    if user_roles:
                        actor_roles = list(user_roles) if not isinstance(user_roles, list) else user_roles
                tenant_id = getattr(request.state, "tenant_uuid", None)
                # Also check for roles directly on request state
                if not actor_roles:
                    state_roles = getattr(request.state, "roles", None)
                    if state_roles:
                        actor_roles = list(state_roles) if not isinstance(state_roles, list) else state_roles

            start_time = time.monotonic()
            success = True
            error_message: str | None = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                duration_ms = int((time.monotonic() - start_time) * 1000)

                try:
                    async with get_async_session() as session:
                        audit_service = AuditService(session)
                        await audit_service.log(
                            action=action,
                            entity_type=entity_type,
                            entity_id=entity_id,
                            user_id=user_id,
                            actor_roles=actor_roles,
                            tenant_id=tenant_id,
                            old_values=old_values, # type: ignore
                            new_values=new_values, # type: ignore
                            ip_address=request.client.host if request and request.client else None,
                            user_agent=request.headers.get("user-agent") if request else None,
                            request_id=getattr(request.state, "request_id", None) if request else None,
                            endpoint=str(request.url.path) if request else None,
                            method=request.method if request else None,
                            success=success,
                            error_message=error_message,
                            duration_ms=duration_ms,
                        )
                except Exception as audit_error:
                    logger.warning(f"Failed to create audit log: {audit_error}")

        return wrapper

    return decorator


class AuditContext:
    """Context manager for manual audit logging.

    Provides a way to manually log audit entries with full control
    over timing and context.

    Example:
        async with AuditContext(
            action=AuditAction.UPDATE,
            entity_type="reminder",
            entity_id="123",
        ) as ctx:
            ctx.set_old_values(old_reminder.dict())
            updated = await repository.update(reminder)
            ctx.set_new_values(updated.dict())
    """

    def __init__(
        self,
        action: AuditAction,
        entity_type: str,
        entity_id: str | None = None,
        user_id: str | None = None,
        actor_roles: list[str] | None = None,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Initialize audit context.

        Args:
            action: Audit action type.
            entity_type: Type of entity.
            entity_id: Entity ID.
            user_id: User performing the action.
            actor_roles: Roles the user had at time of action.
            tenant_id: Tenant context.
            request_id: Request correlation ID.
        """
        self.action = action
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.user_id = user_id
        self.actor_roles = actor_roles or []
        self.tenant_id = tenant_id
        self.request_id = request_id

        self.old_values: dict[str, Any] | None = None
        self.new_values: dict[str, Any] | None = None
        self.metadata: dict[str, Any] = {}
        self.success = True
        self.error_message: str | None = None

        self._start_time: float | None = None
        self._session = None

    def set_actor_roles(self, roles: list[str]) -> None:
        """Set the actor roles for the audit entry."""
        self.actor_roles = roles

    def set_old_values(self, values: dict[str, Any]) -> None:
        """Set the old values for the audit entry."""
        self.old_values = values

    def set_new_values(self, values: dict[str, Any]) -> None:
        """Set the new values for the audit entry."""
        self.new_values = values

    def add_metadata(self, key: str, value: Any) -> None:
        """Add metadata to the audit entry."""
        self.metadata[key] = value

    def set_entity_id(self, entity_id: str) -> None:
        """Set the entity ID (useful when ID is generated during the operation)."""
        self.entity_id = entity_id

    def mark_failed(self, error: str) -> None:
        """Mark the operation as failed."""
        self.success = False
        self.error_message = error

    async def __aenter__(self) -> AuditContext:
        """Enter the audit context."""
        self._start_time = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: # type: ignore
        """Exit the audit context and log the entry."""
        from example_service.infra.database.session import get_async_session

        from .service import AuditService

        if exc_val is not None:
            self.success = False
            self.error_message = str(exc_val)

        duration_ms = None
        if self._start_time is not None:
            duration_ms = int((time.monotonic() - self._start_time) * 1000)

        try:
            async with get_async_session() as session:
                audit_service = AuditService(session)
                await audit_service.log(
                    action=self.action,
                    entity_type=self.entity_type,
                    entity_id=self.entity_id,
                    user_id=self.user_id,
                    actor_roles=self.actor_roles,
                    tenant_id=self.tenant_id,
                    old_values=self.old_values,
                    new_values=self.new_values,
                    request_id=self.request_id,
                    metadata=self.metadata if self.metadata else None,
                    success=self.success,
                    error_message=self.error_message,
                    duration_ms=duration_ms,
                )
        except Exception as e:
            logger.warning(f"Failed to create audit log in context: {e}")
