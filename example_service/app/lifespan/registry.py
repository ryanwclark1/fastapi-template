"""Lifecycle registry for managing startup and shutdown ordering.

This module provides a registry system that manages the execution order
of startup and shutdown hooks based on dependencies and explicit ordering.
"""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


class LifecycleHook:
    """Represents a startup or shutdown hook with metadata."""

    def __init__(
        self,
        name: str,
        func: Callable[..., Awaitable[None]],
        order: int,
        requires: list[str],
    ) -> None:
        """Initialize lifecycle hook.

        Args:
            name: Unique name for this hook
            func: Async function to execute
            order: Startup execution order (lower runs first)
            requires: List of hook names that must run before this one
        """
        self.name = name
        self.func = func
        self.startup_order = order
        self.requires = requires
        # Shutdown order is automatically the inverse of startup order
        # (what starts first, shuts down last)
        self.shutdown_order = 1000 - order
        self.started = False

    async def execute(self, **kwargs: Any) -> None:
        """Execute the hook with provided keyword arguments.

        Args:
            **kwargs: Arguments to pass to the hook function
        """
        await self.func(**kwargs)
        self.started = True


class LifecycleRegistry:
    """Registry for managing application lifecycle hooks.

    Handles registration and execution of startup/shutdown hooks with
    dependency resolution and ordering.

    Example:
        registry = LifecycleRegistry()

        @registry.register(
            name="database",
            startup_order=10,
            requires=["core"],
        )
        async def startup_database(settings: DBSettings, mock_settings: MockSettings) -> None:
            if not settings.is_configured or mock_settings.enabled:
                return
            await init_database()

        @registry.register(name="database")
        async def shutdown_database(settings: DBSettings, mock_settings: MockSettings) -> None:
            if not settings.is_configured or mock_settings.enabled:
                return
            await close_database()

        # Execute all startup hooks in order
        await registry.startup(**all_settings)

        # Execute all shutdown hooks in reverse order
        await registry.shutdown(**all_settings)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._startup_hooks: dict[str, LifecycleHook] = {}
        self._shutdown_hooks: dict[str, LifecycleHook] = {}

    def register(
        self,
        name: str,
        startup_order: int = 50,
        requires: list[str] | None = None,
    ) -> Callable[[Callable[..., Awaitable[None]]], Callable[..., Awaitable[None]]]:
        """Register a lifecycle hook.

        Can be used as a decorator to register startup and shutdown functions.
        Shutdown order is automatically the inverse of startup order.

        Args:
            name: Unique name for this hook (must match for startup/shutdown pairs)
            startup_order: Execution order for startup (lower runs first).
                Shutdown order is automatically 1000 - startup_order.
            requires: List of hook names that must run before this one

        Returns:
            Decorator function

        Example:
            @registry.register(
                name="database",
                startup_order=10,
                requires=["core"],
            )
            async def startup_database(settings: DBSettings) -> None:
                ...

            @registry.register(name="database")
            async def shutdown_database(settings: DBSettings) -> None:
                ...
        """
        requires_list = requires or []

        def decorator(
            func: Callable[..., Awaitable[None]],
        ) -> Callable[..., Awaitable[None]]:
            # Determine if this is a startup or shutdown hook based on function name
            func_name = func.__name__.lower()
            is_shutdown = func_name.startswith("shutdown") or func_name.endswith(
                "_shutdown"
            )

            hook = LifecycleHook(
                name=name,
                func=func,
                order=startup_order,
                requires=requires_list,
            )

            if is_shutdown:
                if name in self._shutdown_hooks:
                    raise ValueError(f"Shutdown hook '{name}' already registered")
                self._shutdown_hooks[name] = hook
            else:
                if name in self._startup_hooks:
                    raise ValueError(f"Startup hook '{name}' already registered")
                self._startup_hooks[name] = hook

            return func

        return decorator

    def _resolve_startup_order(self) -> list[str]:
        """Resolve startup execution order based on dependencies.

        Returns:
            List of hook names in execution order

        Raises:
            ValueError: If circular dependencies or missing dependencies detected
        """
        # Build dependency graph
        remaining = set(self._startup_hooks.keys())
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(name: str, path: set[str]) -> None:
            if name in path:
                msg = f"Circular dependency detected: {' -> '.join(path)} -> {name}"
                raise ValueError(msg)
            if name in visited:
                return

            visited.add(name)
            path.add(name)

            hook = self._startup_hooks[name]
            for dep in hook.requires:
                if dep not in self._startup_hooks:
                    raise ValueError(
                        f"Hook '{name}' requires '{dep}' but it's not registered"
                    )
                visit(dep, path.copy())

            ordered.append(name)
            remaining.discard(name)

        # Visit all hooks
        while remaining:
            # Start with hooks that have no dependencies or whose dependencies are satisfied
            available = [
                name
                for name in remaining
                if all(dep in ordered for dep in self._startup_hooks[name].requires)
            ]
            if not available:
                # No available hooks - check for cycles
                visit(next(iter(remaining)), set())

            # Sort available hooks by order
            available.sort(key=lambda n: self._startup_hooks[n].startup_order)
            for name in available:
                visit(name, set())

        return ordered

    def _resolve_shutdown_order(self) -> list[str]:
        """Resolve shutdown execution order (reverse of startup, respecting shutdown_order).

        Returns:
            List of hook names in shutdown execution order
        """
        # Get all started hooks that have shutdown handlers
        started = [
            name
            for name, hook in self._startup_hooks.items()
            if hook.started and name in self._shutdown_hooks
        ]

        # Sort by shutdown_order (higher first = reverse order)
        return sorted(
            started, key=lambda n: self._shutdown_hooks[n].shutdown_order, reverse=True
        )

    async def startup(self, **kwargs: Any) -> None:
        """Execute all startup hooks in dependency order.

        Args:
            **kwargs: Arguments to pass to all hooks (typically settings objects)
        """
        order = self._resolve_startup_order()

        for name in order:
            hook = self._startup_hooks[name]
            try:
                logger.debug("Starting %s...", name)
                await hook.execute(**kwargs)
                logger.debug("Started %s", name)
            except Exception as e:
                logger.error("Failed to start %s: %s", name, e, exc_info=True)
                raise

    async def shutdown(self, **kwargs: Any) -> None:
        """Execute all shutdown hooks in reverse order.

        Args:
            **kwargs: Arguments to pass to all hooks (typically settings objects)
        """
        order = self._resolve_shutdown_order()

        for name in order:
            hook = self._shutdown_hooks[name]
            try:
                logger.debug("Shutting down %s...", name)
                await hook.execute(**kwargs)
                logger.debug("Shut down %s", name)
            except Exception as e:
                logger.warning("Error shutting down %s: %s", name, e, exc_info=True)
                # Continue shutdown even if one hook fails

    def clear(self) -> None:
        """Clear all registered hooks (mainly for testing)."""
        self._startup_hooks.clear()
        self._shutdown_hooks.clear()


# Global registry instance
lifespan_registry = LifecycleRegistry()

__all__ = ["LifecycleHook", "LifecycleRegistry", "lifespan_registry"]
