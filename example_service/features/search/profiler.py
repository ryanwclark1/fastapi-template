"""Search query performance profiling.

Provides detailed performance monitoring and slow query detection:
- Query execution time tracking
- Slow query logging and alerting
- Performance metrics aggregation
- Query plan analysis helpers

Usage:
    profiler = QueryProfiler(session)

    async with profiler.profile("search_query") as ctx:
        results = await execute_search()
        ctx.set_metadata({"query": query, "results": len(results)})

    # Get slow queries
    slow = await profiler.get_slow_queries(threshold_ms=500)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any, AsyncGenerator

from sqlalchemy import Float, Integer, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class QueryProfile(TimestampedBase):
    """Model for storing query performance profiles."""

    __tablename__ = "search_query_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    query_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    execution_time_ms: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    is_slow: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    entity_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


@dataclass
class ProfileContext:
    """Context for an active profile."""

    query_type: str
    start_time: float = field(default_factory=time.perf_counter)
    query_text: str | None = None
    entity_types: list[str] | None = None
    result_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _end_time: float | None = field(default=None, init=False)

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        end = self._end_time or time.perf_counter()
        return (end - self.start_time) * 1000

    def set_query(self, query: str) -> None:
        """Set the query text."""
        self.query_text = query

    def set_entity_types(self, types: list[str]) -> None:
        """Set the entity types searched."""
        self.entity_types = types

    def set_result_count(self, count: int) -> None:
        """Set the result count."""
        self.result_count = count

    def set_metadata(self, data: dict[str, Any]) -> None:
        """Set additional metadata."""
        self.metadata.update(data)

    def finish(self) -> None:
        """Mark the profile as finished."""
        self._end_time = time.perf_counter()


@dataclass
class PerformanceStats:
    """Aggregated performance statistics."""

    query_type: str
    total_queries: int
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    slow_query_count: int
    slow_query_rate: float


@dataclass
class SlowQueryAlert:
    """Alert for a slow query."""

    query_type: str
    query_text: str | None
    execution_time_ms: float
    threshold_ms: float
    timestamp: datetime
    metadata: dict[str, Any]


class QueryProfiler:
    """Performance profiler for search queries.

    Tracks query execution times, identifies slow queries, and provides
    performance metrics for monitoring and optimization.

    Example:
        profiler = QueryProfiler(session, slow_threshold_ms=500)

        # Profile a query
        async with profiler.profile("fts_search") as ctx:
            ctx.set_query("python tutorial")
            results = await search(query)
            ctx.set_result_count(len(results))

        # Check for slow queries
        slow = await profiler.get_slow_queries(days=7)
    """

    def __init__(
        self,
        session: AsyncSession,
        slow_threshold_ms: float = 500,
        enable_logging: bool = True,
        enable_persistence: bool = True,
        log_slow_queries: bool = True,
        alert_callback: Any | None = None,
    ) -> None:
        """Initialize the profiler.

        Args:
            session: Database session.
            slow_threshold_ms: Threshold for slow queries.
            enable_logging: Log profile results.
            enable_persistence: Save profiles to database.
            log_slow_queries: Log warnings for slow queries.
            alert_callback: Callback for slow query alerts.
        """
        self.session = session
        self.slow_threshold_ms = slow_threshold_ms
        self.enable_logging = enable_logging
        self.enable_persistence = enable_persistence
        self.log_slow_queries = log_slow_queries
        self.alert_callback = alert_callback

    @asynccontextmanager
    async def profile(
        self,
        query_type: str,
    ) -> AsyncGenerator[ProfileContext, None]:
        """Context manager for profiling a query.

        Args:
            query_type: Type of query being profiled.

        Yields:
            ProfileContext for setting query details.
        """
        ctx = ProfileContext(query_type=query_type)

        try:
            yield ctx
        finally:
            ctx.finish()
            await self._record_profile(ctx)

    async def _record_profile(self, ctx: ProfileContext) -> None:
        """Record a completed profile.

        Args:
            ctx: Completed profile context.
        """
        elapsed = ctx.elapsed_ms
        is_slow = elapsed >= self.slow_threshold_ms

        # Log if enabled
        if self.enable_logging:
            level = logging.WARNING if is_slow else logging.DEBUG
            logger.log(
                level,
                "Query profile: type=%s, time=%.2fms, slow=%s, results=%s",
                ctx.query_type,
                elapsed,
                is_slow,
                ctx.result_count,
            )

        # Alert on slow queries
        if is_slow and self.log_slow_queries:
            logger.warning(
                "Slow query detected: type=%s, query=%s, time=%.2fms (threshold=%.2fms)",
                ctx.query_type,
                ctx.query_text,
                elapsed,
                self.slow_threshold_ms,
            )

            if self.alert_callback:
                alert = SlowQueryAlert(
                    query_type=ctx.query_type,
                    query_text=ctx.query_text,
                    execution_time_ms=elapsed,
                    threshold_ms=self.slow_threshold_ms,
                    timestamp=datetime.now(UTC),
                    metadata=ctx.metadata,
                )
                try:
                    if asyncio.iscoroutinefunction(self.alert_callback):
                        await self.alert_callback(alert)
                    else:
                        self.alert_callback(alert)
                except Exception as e:
                    logger.warning("Failed to call slow query alert callback: %s", e)

        # Persist to database
        if self.enable_persistence:
            try:
                profile = QueryProfile(
                    query_type=ctx.query_type,
                    query_text=ctx.query_text[:1000] if ctx.query_text else None,
                    execution_time_ms=elapsed,
                    is_slow=is_slow,
                    entity_types=ctx.entity_types,
                    result_count=ctx.result_count,
                    profile_data=ctx.metadata,
                )
                self.session.add(profile)
                await self.session.flush()
            except Exception as e:
                logger.warning("Failed to persist query profile: %s", e)

    async def get_slow_queries(
        self,
        days: int = 7,
        limit: int = 50,
        query_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent slow queries.

        Args:
            days: Number of days to analyze.
            limit: Maximum results.
            query_type: Optional filter by query type.

        Returns:
            List of slow query records.
        """
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = select(QueryProfile).where(
            QueryProfile.is_slow.is_(True),
            QueryProfile.created_at >= since,
        )

        if query_type:
            stmt = stmt.where(QueryProfile.query_type == query_type)

        stmt = stmt.order_by(QueryProfile.execution_time_ms.desc()).limit(limit)

        try:
            result = await self.session.execute(stmt)
            profiles = result.scalars().all()

            return [
                {
                    "id": p.id,
                    "query_type": p.query_type,
                    "query_text": p.query_text,
                    "execution_time_ms": p.execution_time_ms,
                    "result_count": p.result_count,
                    "timestamp": p.created_at.isoformat() if p.created_at else None,
                    "metadata": p.profile_data,
                }
                for p in profiles
            ]
        except Exception as e:
            logger.warning("Failed to get slow queries: %s", e)
            return []

    async def get_performance_stats(
        self,
        query_type: str | None = None,
        days: int = 7,
    ) -> list[PerformanceStats]:
        """Get aggregated performance statistics.

        Args:
            query_type: Optional filter by query type.
            days: Number of days to analyze.

        Returns:
            List of performance stats by query type.
        """
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = select(
            QueryProfile.query_type,
            func.count().label("total"),
            func.avg(QueryProfile.execution_time_ms).label("avg_time"),
            func.min(QueryProfile.execution_time_ms).label("min_time"),
            func.max(QueryProfile.execution_time_ms).label("max_time"),
            func.sum(func.cast(QueryProfile.is_slow, Integer)).label("slow_count"),
        ).where(QueryProfile.created_at >= since)

        if query_type:
            stmt = stmt.where(QueryProfile.query_type == query_type)

        stmt = stmt.group_by(QueryProfile.query_type)

        try:
            result = await self.session.execute(stmt)
            rows = result.all()

            stats = []
            for row in rows:
                total = row[1]
                slow_count = row[5] or 0

                # Get percentiles (requires additional queries)
                percentiles = await self._get_percentiles(row[0], since)

                stats.append(
                    PerformanceStats(
                        query_type=row[0],
                        total_queries=total,
                        avg_time_ms=float(row[2] or 0),
                        min_time_ms=float(row[3] or 0),
                        max_time_ms=float(row[4] or 0),
                        p50_time_ms=percentiles.get("p50", 0),
                        p95_time_ms=percentiles.get("p95", 0),
                        p99_time_ms=percentiles.get("p99", 0),
                        slow_query_count=slow_count,
                        slow_query_rate=slow_count / total if total > 0 else 0,
                    )
                )

            return stats
        except Exception as e:
            logger.warning("Failed to get performance stats: %s", e)
            return []

    async def _get_percentiles(
        self,
        query_type: str,
        since: datetime,
    ) -> dict[str, float]:
        """Get percentile values for a query type.

        Args:
            query_type: Query type to analyze.
            since: Start date.

        Returns:
            Dictionary with percentile values.
        """
        try:
            # Use PostgreSQL percentile_cont
            stmt = select(
                func.percentile_cont(0.5).within_group(QueryProfile.execution_time_ms).label("p50"),
                func.percentile_cont(0.95).within_group(QueryProfile.execution_time_ms).label("p95"),
                func.percentile_cont(0.99).within_group(QueryProfile.execution_time_ms).label("p99"),
            ).where(
                QueryProfile.query_type == query_type,
                QueryProfile.created_at >= since,
            )

            result = await self.session.execute(stmt)
            row = result.first()

            if row:
                return {
                    "p50": float(row[0] or 0),
                    "p95": float(row[1] or 0),
                    "p99": float(row[2] or 0),
                }
        except Exception as e:
            logger.debug("Failed to get percentiles: %s", e)

        return {"p50": 0, "p95": 0, "p99": 0}

    async def cleanup_old_profiles(
        self,
        days: int = 30,
    ) -> int:
        """Delete old profile records.

        Args:
            days: Delete records older than this.

        Returns:
            Number of records deleted.
        """
        from sqlalchemy import delete

        cutoff = datetime.now(UTC) - timedelta(days=days)

        stmt = delete(QueryProfile).where(QueryProfile.created_at < cutoff)

        try:
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount  # type: ignore
        except Exception as e:
            logger.warning("Failed to cleanup old profiles: %s", e)
            return 0


__all__ = [
    "PerformanceStats",
    "ProfileContext",
    "QueryProfile",
    "QueryProfiler",
    "SlowQueryAlert",
]
