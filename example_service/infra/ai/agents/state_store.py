# mypy: disable-error-code="arg-type,return-value,assignment,attr-defined,misc,no-any-return,override"
"""Persistent state store for AI agents.

This module provides state persistence for:
- Cross-run data sharing (cache results between runs)
- Agent memory persistence
- Workflow state checkpointing
- Multi-tenant state isolation

Storage Backends:
- InMemoryStateStore: For testing and development
- RedisStateStore: For production with Redis
- DatabaseStateStore: For production with PostgreSQL

Example:
    from example_service.infra.ai.agents.state_store import (
        RedisStateStore,
        StateKey,
    )

    store = RedisStateStore(redis_client)

    # Store data with TTL
    await store.set(
        StateKey(tenant_id="t1", namespace="research", key="results"),
        value={"findings": [...]},
        ttl_seconds=3600,
    )

    # Retrieve data
    data = await store.get(
        StateKey(tenant_id="t1", namespace="research", key="results")
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from example_service.infra.cache import RedisCache

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class StateKey:
    """Key for state storage.

    Keys are structured to support multi-tenancy and namespacing.
    """

    tenant_id: str
    namespace: str
    key: str
    version: str = "v1"

    def __str__(self) -> str:
        """Get string representation."""
        return f"{self.tenant_id}:{self.namespace}:{self.key}:{self.version}"

    def to_redis_key(self) -> str:
        """Get Redis-compatible key."""
        return f"ai:state:{self}"

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "namespace": self.namespace,
            "key": self.key,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> StateKey:
        """Create from dictionary."""
        return cls(
            tenant_id=data["tenant_id"],
            namespace=data["namespace"],
            key=data["key"],
            version=data.get("version", "v1"),
        )

    @classmethod
    def from_string(cls, key_str: str) -> StateKey:
        """Parse from string representation."""
        parts = key_str.split(":")
        if len(parts) < 3:
            msg = f"Invalid state key format: {key_str}"
            raise ValueError(msg)
        return cls(
            tenant_id=parts[0],
            namespace=parts[1],
            key=parts[2],
            version=parts[3] if len(parts) > 3 else "v1",
        )


@dataclass
class StateEntry[T]:
    """An entry in the state store."""

    key: StateKey
    value: T
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize entry."""
        return {
            "key": self.key.to_dict(),
            "value": self.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateEntry[Any]:
        """Deserialize entry."""
        return cls(
            key=StateKey.from_dict(data["key"]),
            value=data["value"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            metadata=data.get("metadata", {}),
        )


class BaseStateStore(ABC):
    """Abstract base class for state stores."""

    @abstractmethod
    async def get(self, key: StateKey) -> Any | None:
        """Get value by key.

        Args:
            key: State key

        Returns:
            Value if exists and not expired, None otherwise
        """

    @abstractmethod
    async def set(
        self,
        key: StateKey,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set value by key.

        Args:
            key: State key
            value: Value to store (must be JSON-serializable)
            ttl_seconds: Time-to-live in seconds (None = no expiry)
            metadata: Additional metadata to store
        """

    @abstractmethod
    async def delete(self, key: StateKey) -> bool:
        """Delete value by key.

        Args:
            key: State key

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def exists(self, key: StateKey) -> bool:
        """Check if key exists.

        Args:
            key: State key

        Returns:
            True if exists and not expired
        """

    @abstractmethod
    async def list_keys(
        self,
        tenant_id: str,
        namespace: str | None = None,
        pattern: str | None = None,
    ) -> list[StateKey]:
        """List keys matching criteria.

        Args:
            tenant_id: Tenant ID (required)
            namespace: Optional namespace filter
            pattern: Optional key pattern (supports * wildcard)

        Returns:
            List of matching keys
        """

    @abstractmethod
    async def clear_namespace(
        self,
        tenant_id: str,
        namespace: str,
    ) -> int:
        """Clear all keys in a namespace.

        Args:
            tenant_id: Tenant ID
            namespace: Namespace to clear

        Returns:
            Number of keys deleted
        """

    async def get_or_set(
        self,
        key: StateKey,
        factory: callable[[], Any],
        ttl_seconds: int | None = None,
    ) -> Any:
        """Get value or compute and set if missing.

        Args:
            key: State key
            factory: Function to compute value if missing
            ttl_seconds: TTL for new value

        Returns:
            Existing or newly computed value
        """
        value = await self.get(key)
        if value is not None:
            return value

        value = factory()
        if hasattr(value, "__await__"):
            value = await value

        await self.set(key, value, ttl_seconds=ttl_seconds)
        return value

    async def increment(
        self,
        key: StateKey,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Increment a numeric value.

        Args:
            key: State key
            amount: Amount to increment by
            ttl_seconds: TTL (only applies if key doesn't exist)

        Returns:
            New value after increment
        """
        current = await self.get(key)
        new_value = (current or 0) + amount
        await self.set(key, new_value, ttl_seconds=ttl_seconds)
        return new_value


class InMemoryStateStore(BaseStateStore):
    """In-memory state store for testing and development.

    Not suitable for production - data is lost on restart.
    """

    def __init__(self) -> None:
        self._store: dict[str, StateEntry[Any]] = {}

    async def get(self, key: StateKey) -> Any | None:
        """Get value by key."""
        key_str = str(key)
        entry = self._store.get(key_str)

        if entry is None:
            return None

        if entry.is_expired:
            del self._store[key_str]
            return None

        return entry.value

    async def set(
        self,
        key: StateKey,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set value by key."""
        key_str = str(key)
        now = datetime.now(UTC)

        expires_at = None
        if ttl_seconds is not None:
            expires_at = now + timedelta(seconds=ttl_seconds)

        existing = self._store.get(key_str)
        created_at = existing.created_at if existing else now

        self._store[key_str] = StateEntry(
            key=key,
            value=value,
            created_at=created_at,
            updated_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    async def delete(self, key: StateKey) -> bool:
        """Delete value by key."""
        key_str = str(key)
        if key_str in self._store:
            del self._store[key_str]
            return True
        return False

    async def exists(self, key: StateKey) -> bool:
        """Check if key exists."""
        key_str = str(key)
        entry = self._store.get(key_str)
        if entry is None:
            return False
        if entry.is_expired:
            del self._store[key_str]
            return False
        return True

    async def list_keys(
        self,
        tenant_id: str,
        namespace: str | None = None,
        pattern: str | None = None,
    ) -> list[StateKey]:
        """List keys matching criteria."""
        keys = []
        prefix = f"{tenant_id}:"
        if namespace:
            prefix += f"{namespace}:"

        for key_str, entry in list(self._store.items()):
            if entry.is_expired:
                del self._store[key_str]
                continue

            if not key_str.startswith(prefix):
                continue

            if pattern:
                # Simple wildcard matching
                import fnmatch
                if not fnmatch.fnmatch(key_str, f"*{pattern}*"):
                    continue

            keys.append(entry.key)

        return keys

    async def clear_namespace(
        self,
        tenant_id: str,
        namespace: str,
    ) -> int:
        """Clear all keys in namespace."""
        prefix = f"{tenant_id}:{namespace}:"
        to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)

    def clear_all(self) -> None:
        """Clear entire store (for testing)."""
        self._store.clear()


class RedisStateStore(BaseStateStore):
    """Redis-backed state store for production.

    Features:
    - Automatic TTL expiration
    - Atomic operations
    - Pattern-based key listing
    """

    def __init__(
        self,
        redis: Redis,  # type: ignore[type-arg]
        key_prefix: str = "ai:state",
    ) -> None:
        """Initialize Redis state store.

        Args:
            redis: Async Redis client
            key_prefix: Prefix for all keys
        """
        self._redis = redis
        self._key_prefix = key_prefix

    def _make_key(self, key: StateKey) -> str:
        """Create Redis key from StateKey."""
        return f"{self._key_prefix}:{key}"

    async def get(self, key: StateKey) -> Any | None:
        """Get value by key."""
        redis_key = self._make_key(key)
        data = await self._redis.get(redis_key)

        if data is None:
            return None

        try:
            entry = json.loads(data)
            return entry.get("value")
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode state for key: {key}")
            return None

    async def set(
        self,
        key: StateKey,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set value by key."""
        redis_key = self._make_key(key)
        now = datetime.now(UTC)

        entry = {
            "key": key.to_dict(),
            "value": value,
            "updated_at": now.isoformat(),
            "metadata": metadata or {},
        }

        data = json.dumps(entry, default=str)

        if ttl_seconds is not None:
            await self._redis.setex(redis_key, ttl_seconds, data)
        else:
            await self._redis.set(redis_key, data)

    async def delete(self, key: StateKey) -> bool:
        """Delete value by key."""
        redis_key = self._make_key(key)
        result = await self._redis.delete(redis_key)
        return result > 0

    async def exists(self, key: StateKey) -> bool:
        """Check if key exists."""
        redis_key = self._make_key(key)
        return await self._redis.exists(redis_key) > 0

    async def list_keys(
        self,
        tenant_id: str,
        namespace: str | None = None,
        pattern: str | None = None,
    ) -> list[StateKey]:
        """List keys matching criteria."""
        search_pattern = f"{self._key_prefix}:{tenant_id}:"
        if namespace:
            search_pattern += f"{namespace}:"
        if pattern:
            search_pattern += f"*{pattern}*"
        else:
            search_pattern += "*"

        keys = []
        async for redis_key in self._redis.scan_iter(search_pattern):
            # Extract StateKey from Redis key
            key_str = redis_key.decode() if isinstance(redis_key, bytes) else redis_key
            key_str = key_str.removeprefix(f"{self._key_prefix}:")
            try:
                state_key = StateKey.from_string(key_str)
                keys.append(state_key)
            except ValueError:
                continue

        return keys

    async def clear_namespace(
        self,
        tenant_id: str,
        namespace: str,
    ) -> int:
        """Clear all keys in namespace."""
        pattern = f"{self._key_prefix}:{tenant_id}:{namespace}:*"
        count = 0

        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)
            count += 1

        return count

    async def increment(
        self,
        key: StateKey,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Atomic increment."""
        redis_key = self._make_key(key)

        # Use Redis INCRBY for atomicity
        # Note: This only works for simple numeric values
        # For complex values, use get/set with locking

        pipe = self._redis.pipeline()
        pipe.incrby(redis_key, amount)
        if ttl_seconds:
            pipe.expire(redis_key, ttl_seconds)

        results = await pipe.execute()
        return results[0]


class ScopedStateStore:
    """State store scoped to a tenant and namespace.

    Provides a convenient wrapper for agent-specific state.

    Example:
        scoped = ScopedStateStore(
            store=redis_store,
            tenant_id="tenant-123",
            namespace="research_agent",
        )

        await scoped.set("results", {"data": [...]})
        results = await scoped.get("results")
    """

    def __init__(
        self,
        store: BaseStateStore,
        tenant_id: str,
        namespace: str,
        default_ttl: int | None = None,
    ) -> None:
        """Initialize scoped store.

        Args:
            store: Underlying state store
            tenant_id: Tenant ID
            namespace: Namespace for this scope
            default_ttl: Default TTL for new entries
        """
        self._store = store
        self._tenant_id = tenant_id
        self._namespace = namespace
        self._default_ttl = default_ttl

    def _make_key(self, key: str, version: str = "v1") -> StateKey:
        """Create StateKey from simple key."""
        return StateKey(
            tenant_id=self._tenant_id,
            namespace=self._namespace,
            key=key,
            version=version,
        )

    async def get(self, key: str, version: str = "v1") -> Any | None:
        """Get value by simple key."""
        return await self._store.get(self._make_key(key, version))

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        version: str = "v1",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set value by simple key."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await self._store.set(
            self._make_key(key, version),
            value,
            ttl_seconds=ttl,
            metadata=metadata,
        )

    async def delete(self, key: str, version: str = "v1") -> bool:
        """Delete value by simple key."""
        return await self._store.delete(self._make_key(key, version))

    async def exists(self, key: str, version: str = "v1") -> bool:
        """Check if key exists."""
        return await self._store.exists(self._make_key(key, version))

    async def list_keys(self, pattern: str | None = None) -> list[str]:
        """List keys in this scope."""
        state_keys = await self._store.list_keys(
            tenant_id=self._tenant_id,
            namespace=self._namespace,
            pattern=pattern,
        )
        return [k.key for k in state_keys]

    async def clear(self) -> int:
        """Clear all keys in this scope."""
        return await self._store.clear_namespace(
            self._tenant_id,
            self._namespace,
        )

    async def get_or_set(
        self,
        key: str,
        factory: callable[[], Any],
        ttl_seconds: int | None = None,
        version: str = "v1",
    ) -> Any:
        """Get or compute and set value."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        return await self._store.get_or_set(
            self._make_key(key, version),
            factory,
            ttl_seconds=ttl,
        )


class RedisCacheStateStore(BaseStateStore):
    """State store using the existing RedisCache infrastructure.

    This integrates with the application's existing Redis cache setup,
    providing connection pooling, retry logic, and metrics.

    Example:
        from example_service.infra.cache import get_cache_instance
        from example_service.infra.ai.agents.state_store import (
            RedisCacheStateStore,
            configure_state_store,
        )

        # Configure to use existing Redis cache
        cache = get_cache_instance()
        if cache:
            store = RedisCacheStateStore(cache)
            configure_state_store(store)
    """

    def __init__(
        self,
        cache: RedisCache,  # type: ignore[name-defined]
        key_prefix: str = "ai:state",
    ) -> None:
        """Initialize Redis cache state store.

        Args:
            cache: RedisCache instance from infra/cache
            key_prefix: Prefix for all state keys
        """
        self._cache = cache
        self._key_prefix = key_prefix

    def _make_key(self, key: StateKey) -> str:
        """Create Redis key from StateKey."""
        return f"{self._key_prefix}:{key}"

    async def get(self, key: StateKey) -> Any | None:
        """Get value by key."""
        redis_key = self._make_key(key)
        data = await self._cache.client.get(redis_key)

        if data is None:
            return None

        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            entry = json.loads(data)
            return entry.get("value")
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode state for key: {key}")
            return None

    async def set(
        self,
        key: StateKey,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set value by key."""
        redis_key = self._make_key(key)
        now = datetime.now(UTC)

        entry = {
            "key": key.to_dict(),
            "value": value,
            "updated_at": now.isoformat(),
            "metadata": metadata or {},
        }

        data = json.dumps(entry, default=str)

        if ttl_seconds is not None:
            await self._cache.client.setex(redis_key, ttl_seconds, data)
        else:
            await self._cache.client.set(redis_key, data)

    async def delete(self, key: StateKey) -> bool:
        """Delete value by key."""
        redis_key = self._make_key(key)
        result = await self._cache.client.delete(redis_key)
        return result > 0

    async def exists(self, key: StateKey) -> bool:
        """Check if key exists."""
        redis_key = self._make_key(key)
        result = await self._cache.client.exists(redis_key)
        return result > 0

    async def list_keys(
        self,
        tenant_id: str,
        namespace: str | None = None,
        pattern: str | None = None,
    ) -> list[StateKey]:
        """List keys matching criteria."""
        search_pattern = f"{self._key_prefix}:{tenant_id}:"
        if namespace:
            search_pattern += f"{namespace}:"
        if pattern:
            search_pattern += f"*{pattern}*"
        else:
            search_pattern += "*"

        keys = []
        async for redis_key in self._cache.scan_iter(search_pattern):
            key_str = redis_key.decode() if isinstance(redis_key, bytes) else redis_key
            key_str = key_str.removeprefix(f"{self._key_prefix}:")
            try:
                state_key = StateKey.from_string(key_str)
                keys.append(state_key)
            except ValueError:
                continue

        return keys

    async def clear_namespace(
        self,
        tenant_id: str,
        namespace: str,
    ) -> int:
        """Clear all keys in namespace."""
        pattern = f"{self._key_prefix}:{tenant_id}:{namespace}:*"
        return await self._cache.delete_pattern(pattern)

    async def increment(
        self,
        key: StateKey,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Atomic increment."""
        redis_key = self._make_key(key)

        pipe = self._cache.pipeline()
        pipe.incrby(redis_key, amount)
        if ttl_seconds:
            pipe.expire(redis_key, ttl_seconds)

        results = await pipe.execute()
        return results[0]


# Global state store instance
_global_store: BaseStateStore | None = None


def get_state_store() -> BaseStateStore:
    """Get the global state store singleton."""
    global _global_store
    if _global_store is None:
        _global_store = InMemoryStateStore()
    return _global_store


def configure_state_store(store: BaseStateStore | None) -> None:
    """Configure the global state store."""
    global _global_store
    _global_store = store


def reset_state_store() -> None:
    """Reset to default in-memory store."""
    global _global_store
    _global_store = None


async def configure_redis_state_store() -> RedisCacheStateStore | None:
    """Configure state store to use Redis from existing infrastructure.

    This should be called during application startup after Redis is connected.

    Returns:
        RedisCacheStateStore if Redis is available, None otherwise.

    Example:
        # In your application startup
        from example_service.infra.ai.agents.state_store import (
            configure_redis_state_store,
        )

        @app.on_event("startup")
        async def startup():
            await configure_redis_state_store()
    """
    try:
        from example_service.infra.cache import get_cache_instance

        cache = get_cache_instance()
        if cache is None:
            logger.warning(
                "Redis cache not initialized - using in-memory state store. "
                "State will be lost on restart.",
            )
            return None

        store = RedisCacheStateStore(cache)
        configure_state_store(store)
        logger.info("AI state store configured with Redis backend")
        return store

    except ImportError as e:
        logger.warning(f"Could not import Redis cache: {e}")
        return None
    except Exception as e:
        logger.exception(f"Failed to configure Redis state store: {e}")
        return None


def get_state_store_dependency() -> BaseStateStore:
    """FastAPI dependency for getting the state store.

    Usage:
        from example_service.infra.ai.agents.state_store import (
            get_state_store_dependency,
            BaseStateStore,
        )

        @router.get("/state/{key}")
        async def get_state(
            key: str,
            store: BaseStateStore = Depends(get_state_store_dependency),
        ):
            value = await store.get(StateKey(...))
            return {"value": value}
    """
    return get_state_store()
