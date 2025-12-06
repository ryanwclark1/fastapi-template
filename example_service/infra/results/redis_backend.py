"""Redis-based result backends for Taskiq task result storage.

This module provides three Redis backend implementations:
- RedisAsyncResultBackend: Standard Redis deployment
- RedisAsyncClusterResultBackend: Redis Cluster deployment
- RedisAsyncSentinelResultBackend: Redis Sentinel deployment (high availability)

Each backend supports:
- Configurable result expiration times
- Optional result persistence (keep_results flag)
- Task progress tracking
- Custom key prefixes for namespace isolation
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from redis.asyncio import BlockingConnectionPool, Redis, Sentinel
from redis.asyncio.cluster import RedisCluster
from taskiq import AsyncResultBackend
from taskiq.abc.serializer import TaskiqSerializer
from taskiq.compat import model_dump, model_validate
from taskiq.depends.progress_tracker import TaskProgress
from taskiq.result import TaskiqResult
from taskiq.serializers import PickleSerializer

from example_service.infra.results.exceptions import (
    DuplicateExpireTimeSelectedError,
    ExpireTimeMustBeMoreThanZeroError,
    ResultIsMissingError,
)

if TYPE_CHECKING:
    from redis.asyncio.connection import Connection

    type _Redis = Redis[bytes]
    type _BlockingConnectionPool = BlockingConnectionPool[Connection]
else:
    type _Redis = Redis
    type _BlockingConnectionPool = BlockingConnectionPool

_ReturnType = TypeVar("_ReturnType")

PROGRESS_KEY_SUFFIX = "__progress"


class RedisAsyncResultBackend(AsyncResultBackend[_ReturnType]):
    """Async result backend based on Redis.

    This backend stores task results and progress in Redis with support for:
    - Automatic expiration of results (configurable in seconds or milliseconds)
    - Optional persistence of results after reading
    - Task progress tracking
    - Custom key prefixes for multi-tenant scenarios

    Example:
            from example_service.infra.results import RedisAsyncResultBackend

        backend = RedisAsyncResultBackend(
            redis_url="redis://localhost:6379/0",
            result_ex_time=3600,  # Results expire after 1 hour
            prefix_str="myapp",   # All keys prefixed with "myapp:"
        )
    """

    def __init__(
        self,
        redis_url: str,
        keep_results: bool = True,
        result_ex_time: int | None = None,
        result_px_time: int | None = None,
        max_connection_pool_size: int | None = None,
        serializer: TaskiqSerializer | None = None,
        prefix_str: str | None = None,
        **connection_kwargs: Any,
    ) -> None:
        """Constructs a new result backend.

        Args:
            redis_url: URL to Redis server (e.g., "redis://localhost:6379/0").
            keep_results: If True, results remain in Redis after reading. Default: True.
            result_ex_time: Expiration time in seconds for results. Mutually exclusive
                with result_px_time.
            result_px_time: Expiration time in milliseconds for results. Mutually
                exclusive with result_ex_time.
            max_connection_pool_size: Maximum number of connections in the pool.
            serializer: Custom serializer for results. Defaults to PickleSerializer.
            prefix_str: Optional prefix for all Redis keys (useful for namespacing).
            **connection_kwargs: Additional arguments passed to BlockingConnectionPool.

        Raises:
            DuplicateExpireTimeSelectedError: If both result_ex_time and result_px_time
                are provided.
            ExpireTimeMustBeMoreThanZeroError: If expiration time is <= 0.
        """
        self.redis_pool: _BlockingConnectionPool = BlockingConnectionPool.from_url(
            url=redis_url,
            max_connections=max_connection_pool_size,
            **connection_kwargs,
        )
        self.serializer = serializer or PickleSerializer()
        self.keep_results = keep_results
        self.result_ex_time = result_ex_time
        self.result_px_time = result_px_time
        self.prefix_str = prefix_str

        unavailable_conditions = any(
            (
                self.result_ex_time is not None and self.result_ex_time <= 0,
                self.result_px_time is not None and self.result_px_time <= 0,
            ),
        )
        if unavailable_conditions:
            raise ExpireTimeMustBeMoreThanZeroError

        if self.result_ex_time and self.result_px_time:
            raise DuplicateExpireTimeSelectedError

    def _task_name(self, task_id: str) -> str:
        """Generate the Redis key name for a task.

        Args:
            task_id: The task identifier.

        Returns:
            The Redis key name, optionally prefixed.
        """
        if self.prefix_str is None:
            return task_id
        return f"{self.prefix_str}:{task_id}"

    async def startup(self) -> None:
        """Initialize Redis backend.

        Connection pool is already created in __init__, so this is a no-op
        that exists for consistency with AsyncResultBackend interface.
        """

    async def shutdown(self) -> None:
        """Closes Redis connection pool."""
        await self.redis_pool.disconnect()
        await super().shutdown()

    async def set_result(
        self,
        task_id: str,
        result: TaskiqResult[_ReturnType],
    ) -> None:
        """Sets task result in Redis.

        Serializes the TaskiqResult instance and stores it in Redis with
        optional expiration time.

        Args:
            task_id: ID of the task.
            result: TaskiqResult instance containing the task's outcome.
        """
        key = self._task_name(task_id)
        value = self.serializer.dumpb(model_dump(result))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None

        async with Redis(connection_pool=self.redis_pool) as redis:
            await redis.set(key, value, ex=ex, px=px)

    async def is_result_ready(self, task_id: str) -> bool:
        """Checks if a task result is available in Redis.

        Args:
            task_id: ID of the task.

        Returns:
            True if the result exists in Redis, False otherwise.
        """
        async with Redis(connection_pool=self.redis_pool) as redis:
            return bool(await redis.exists(self._task_name(task_id)))

    async def get_result(
        self,
        task_id: str,
        with_logs: bool = False,
    ) -> TaskiqResult[_ReturnType]:
        """Retrieves a task result from Redis.

        Args:
            task_id: Task's unique identifier.
            with_logs: If True, includes task execution logs in the result.

        Returns:
            The task's result.

        Raises:
            ResultIsMissingError: If no result exists for the given task_id.
        """
        task_name = self._task_name(task_id)
        async with Redis(connection_pool=self.redis_pool) as redis:
            if self.keep_results:
                result_value = await redis.get(
                    name=task_name,
                )
            else:
                result_value = await redis.getdel(
                    name=task_name,
                )

        if result_value is None:
            raise ResultIsMissingError

        taskiq_result = model_validate(
            TaskiqResult[_ReturnType],
            self.serializer.loadb(result_value),
        )

        if not with_logs:
            taskiq_result.log = None

        return taskiq_result

    async def set_progress(
        self,
        task_id: str,
        progress: TaskProgress[_ReturnType],
    ) -> None:
        """Sets task progress in Redis.

        Stores progress information with the same expiration settings as results.
        Progress keys are stored with a "__progress" suffix.

        Args:
            task_id: ID of the task.
            progress: TaskProgress instance with current task progress.
        """
        key = self._task_name(task_id) + PROGRESS_KEY_SUFFIX
        value = self.serializer.dumpb(model_dump(progress))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None

        async with Redis(connection_pool=self.redis_pool) as redis:
            await redis.set(key, value, ex=ex, px=px)

    async def get_progress(
        self,
        task_id: str,
    ) -> TaskProgress[_ReturnType] | None:
        """Retrieves task progress from Redis.

        Args:
            task_id: Task's unique identifier.

        Returns:
            TaskProgress instance if progress data exists, None otherwise.
        """
        async with Redis(connection_pool=self.redis_pool) as redis:
            result_value = await redis.get(
                name=self._task_name(task_id) + PROGRESS_KEY_SUFFIX,
            )

        if result_value is None:
            return None

        return model_validate(
            TaskProgress[_ReturnType],
            self.serializer.loadb(result_value),
        )


class RedisAsyncClusterResultBackend(AsyncResultBackend[_ReturnType]):
    """Async result backend based on Redis Cluster.

    Use this backend when your Redis deployment uses cluster mode for
    horizontal scalability and high availability.

    Example:
            backend = RedisAsyncClusterResultBackend(
            redis_url="redis://node1:6379,node2:6379,node3:6379",
            result_ex_time=3600,
        )
    """

    def __init__(
        self,
        redis_url: str,
        keep_results: bool = True,
        result_ex_time: int | None = None,
        result_px_time: int | None = None,
        serializer: TaskiqSerializer | None = None,
        prefix_str: str | None = None,
        **connection_kwargs: Any,
    ) -> None:
        """Constructs a new Redis Cluster result backend.

        Args:
            redis_url: URL to Redis cluster nodes.
            keep_results: If True, results remain after reading. Default: True.
            result_ex_time: Expiration time in seconds.
            result_px_time: Expiration time in milliseconds.
            serializer: Custom serializer. Defaults to PickleSerializer.
            prefix_str: Optional key prefix for namespacing.
            **connection_kwargs: Additional arguments for RedisCluster.

        Raises:
            DuplicateExpireTimeSelectedError: If both expiration times are set.
            ExpireTimeMustBeMoreThanZeroError: If expiration time is <= 0.
        """
        self.redis: Any = RedisCluster.from_url(
            redis_url,
            **connection_kwargs,
        )
        self.serializer = serializer or PickleSerializer()
        self.keep_results = keep_results
        self.result_ex_time = result_ex_time
        self.result_px_time = result_px_time
        self.prefix_str = prefix_str

        unavailable_conditions = any(
            (
                self.result_ex_time is not None and self.result_ex_time <= 0,
                self.result_px_time is not None and self.result_px_time <= 0,
            ),
        )
        if unavailable_conditions:
            raise ExpireTimeMustBeMoreThanZeroError

        if self.result_ex_time and self.result_px_time:
            raise DuplicateExpireTimeSelectedError

    def _task_name(self, task_id: str) -> str:
        """Generate the Redis key name for a task."""
        if self.prefix_str is None:
            return task_id
        return f"{self.prefix_str}:{task_id}"

    async def startup(self) -> None:
        """Initialize Redis Cluster backend.

        Connection is already created in __init__, so this is a no-op
        that exists for consistency with AsyncResultBackend interface.
        """

    async def shutdown(self) -> None:
        """Closes Redis cluster connection."""
        await self.redis.close()
        await super().shutdown()

    async def set_result(
        self,
        task_id: str,
        result: TaskiqResult[_ReturnType],
    ) -> None:
        """Sets task result in Redis cluster."""
        key = self._task_name(task_id)
        value = self.serializer.dumpb(model_dump(result))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None
        await self.redis.set(key, value, ex=ex, px=px)

    async def is_result_ready(self, task_id: str) -> bool:
        """Checks if result is available in Redis cluster."""
        return bool(await self.redis.exists(self._task_name(task_id)))

    async def get_result(
        self,
        task_id: str,
        with_logs: bool = False,
    ) -> TaskiqResult[_ReturnType]:
        """Retrieves task result from Redis cluster."""
        task_name = self._task_name(task_id)
        if self.keep_results:
            result_value = await self.redis.get(
                task_name,
            )
        else:
            result_value = await self.redis.getdel(
                task_name,
            )

        if result_value is None:
            raise ResultIsMissingError

        taskiq_result: TaskiqResult[_ReturnType] = model_validate(
            TaskiqResult[_ReturnType],
            self.serializer.loadb(result_value),
        )

        if not with_logs:
            taskiq_result.log = None

        return taskiq_result

    async def set_progress(
        self,
        task_id: str,
        progress: TaskProgress[_ReturnType],
    ) -> None:
        """Sets task progress in Redis cluster."""
        key = self._task_name(task_id) + PROGRESS_KEY_SUFFIX
        value = self.serializer.dumpb(model_dump(progress))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None
        await self.redis.set(key, value, ex=ex, px=px)

    async def get_progress(
        self,
        task_id: str,
    ) -> TaskProgress[_ReturnType] | None:
        """Retrieves task progress from Redis cluster."""
        result_value = await self.redis.get(
            self._task_name(task_id) + PROGRESS_KEY_SUFFIX,
        )

        if result_value is None:
            return None

        return model_validate(
            TaskProgress[_ReturnType],
            self.serializer.loadb(result_value),
        )


class RedisAsyncSentinelResultBackend(AsyncResultBackend[_ReturnType]):
    """Async result backend based on Redis Sentinel.

    Use this backend for high-availability Redis deployments with automatic
    failover capabilities via Redis Sentinel.

    Example:
            backend = RedisAsyncSentinelResultBackend(
            sentinels=[("sentinel1", 26379), ("sentinel2", 26379)],
            master_name="mymaster",
            result_ex_time=3600,
        )
    """

    def __init__(
        self,
        sentinels: list[tuple[str, int]],
        master_name: str,
        keep_results: bool = True,
        result_ex_time: int | None = None,
        result_px_time: int | None = None,
        min_other_sentinels: int = 0,
        sentinel_kwargs: Any | None = None,
        serializer: TaskiqSerializer | None = None,
        prefix_str: str | None = None,
        **connection_kwargs: Any,
    ) -> None:
        """Constructs a new Redis Sentinel result backend.

        Args:
            sentinels: List of (host, port) tuples for sentinel nodes.
            master_name: Name of the Redis master to connect to.
            keep_results: If True, results remain after reading. Default: True.
            result_ex_time: Expiration time in seconds.
            result_px_time: Expiration time in milliseconds.
            min_other_sentinels: Minimum number of other sentinels required.
            sentinel_kwargs: Additional arguments for Sentinel connection.
            serializer: Custom serializer. Defaults to PickleSerializer.
            prefix_str: Optional key prefix for namespacing.
            **connection_kwargs: Additional arguments for Redis connection pool.

        Raises:
            DuplicateExpireTimeSelectedError: If both expiration times are set.
            ExpireTimeMustBeMoreThanZeroError: If expiration time is <= 0.
        """
        self.sentinel = Sentinel(
            sentinels=sentinels,
            min_other_sentinels=min_other_sentinels,
            sentinel_kwargs=sentinel_kwargs,
            **connection_kwargs,
        )
        self.master_name = master_name
        self.serializer = serializer or PickleSerializer()
        self.keep_results = keep_results
        self.result_ex_time = result_ex_time
        self.result_px_time = result_px_time
        self.prefix_str = prefix_str

        unavailable_conditions = any(
            (
                self.result_ex_time is not None and self.result_ex_time <= 0,
                self.result_px_time is not None and self.result_px_time <= 0,
            ),
        )
        if unavailable_conditions:
            raise ExpireTimeMustBeMoreThanZeroError

        if self.result_ex_time and self.result_px_time:
            raise DuplicateExpireTimeSelectedError

    def _task_name(self, task_id: str) -> str:
        """Generate the Redis key name for a task."""
        if self.prefix_str is None:
            return task_id
        return f"{self.prefix_str}:{task_id}"

    async def startup(self) -> None:
        """Initialize Redis Sentinel backend.

        Sentinel connection is already created in __init__, so this is a no-op
        that exists for consistency with AsyncResultBackend interface.
        """

    @asynccontextmanager
    async def _acquire_master_conn(self) -> AsyncIterator[_Redis]:
        """Acquires a connection to the Redis master via Sentinel."""
        async with self.sentinel.master_for(self.master_name) as redis_conn:
            yield redis_conn

    async def set_result(
        self,
        task_id: str,
        result: TaskiqResult[_ReturnType],
    ) -> None:
        """Sets task result in Redis via Sentinel."""
        key = self._task_name(task_id)
        value = self.serializer.dumpb(model_dump(result))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None

        async with self._acquire_master_conn() as redis:
            await redis.set(key, value, ex=ex, px=px)

    async def is_result_ready(self, task_id: str) -> bool:
        """Checks if result is available in Redis via Sentinel."""
        async with self._acquire_master_conn() as redis:
            return bool(await redis.exists(self._task_name(task_id)))

    async def get_result(
        self,
        task_id: str,
        with_logs: bool = False,
    ) -> TaskiqResult[_ReturnType]:
        """Retrieves task result from Redis via Sentinel."""
        task_name = self._task_name(task_id)
        async with self._acquire_master_conn() as redis:
            if self.keep_results:
                result_value = await redis.get(
                    name=task_name,
                )
            else:
                result_value = await redis.getdel(
                    name=task_name,
                )

        if result_value is None:
            raise ResultIsMissingError

        taskiq_result = model_validate(
            TaskiqResult[_ReturnType],
            self.serializer.loadb(result_value),
        )

        if not with_logs:
            taskiq_result.log = None

        return taskiq_result

    async def set_progress(
        self,
        task_id: str,
        progress: TaskProgress[_ReturnType],
    ) -> None:
        """Sets task progress in Redis via Sentinel."""
        key = self._task_name(task_id) + PROGRESS_KEY_SUFFIX
        value = self.serializer.dumpb(model_dump(progress))
        ex = self.result_ex_time if self.result_ex_time else None
        px = self.result_px_time if self.result_px_time else None

        async with self._acquire_master_conn() as redis:
            await redis.set(key, value, ex=ex, px=px)

    async def get_progress(
        self,
        task_id: str,
    ) -> TaskProgress[_ReturnType] | None:
        """Retrieves task progress from Redis via Sentinel."""
        async with self._acquire_master_conn() as redis:
            result_value = await redis.get(
                name=self._task_name(task_id) + PROGRESS_KEY_SUFFIX,
            )

        if result_value is None:
            return None

        return model_validate(
            TaskProgress[_ReturnType],
            self.serializer.loadb(result_value),
        )

    async def shutdown(self) -> None:
        """Shutdown sentinel connections."""
        for sentinel in self.sentinel.sentinels:
            await sentinel.close()
        await super().shutdown()
