"""Search analytics for tracking and analyzing search patterns.

This module provides functionality for:
- Tracking search queries and their results
- Analyzing popular search terms
- Identifying zero-result queries
- Measuring search effectiveness
- Generating search insights

Usage:
    from example_service.core.database.search.analytics import SearchAnalytics

    analytics = SearchAnalytics(session)

    # Record a search
    await analytics.record_search(
        query="python tutorial",
        results_count=42,
        entity_types=["posts", "articles"],
    )

    # Get popular searches
    popular = await analytics.get_popular_searches(days=7, limit=10)

    # Get zero-result queries
    zero_results = await analytics.get_zero_result_queries(days=7)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SearchQuery(TimestampedBase):
    """Model for storing search query history.

    Tracks all search queries with their results for analytics.
    """

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_text: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_query: Mapped[str] = mapped_column(String(500), nullable=True)
    entity_types: Mapped[list[str]] = mapped_column(JSONB, nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    took_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clicked_result: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    clicked_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicked_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    search_syntax: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_data: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )


class SearchSuggestionLog(TimestampedBase):
    """Model for tracking search suggestion usage."""

    __tablename__ = "search_suggestion_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prefix: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    suggested_text: Mapped[str] = mapped_column(String(500), nullable=False)
    was_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


@dataclass
class SearchStats:
    """Statistics about search usage."""

    total_searches: int = 0
    unique_queries: int = 0
    zero_result_rate: float = 0.0
    avg_results_count: float = 0.0
    avg_response_time_ms: float = 0.0
    click_through_rate: float = 0.0
    top_queries: list[dict[str, Any]] = field(default_factory=list)
    zero_result_queries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SearchInsight:
    """A single search insight or recommendation."""

    type: str  # "improvement", "warning", "info"
    title: str
    description: str
    metric: str | None = None
    value: float | None = None
    recommendation: str | None = None


class SearchAnalytics:
    """Service for search analytics and insights.

    Provides methods to track searches and analyze patterns to
    improve search quality.

    Example:
        analytics = SearchAnalytics(session)

        # Record a search
        await analytics.record_search(
            query="python tutorial",
            results_count=42,
            took_ms=150,
            user_id="user123",
        )

        # Get statistics
        stats = await analytics.get_stats(days=30)
        print(f"Total searches: {stats.total_searches}")
        print(f"Zero-result rate: {stats.zero_result_rate:.1%}")

        # Get insights
        insights = await analytics.generate_insights(days=30)
        for insight in insights:
            print(f"{insight.type}: {insight.title}")
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize analytics service.

        Args:
            session: Database session
        """
        self.session = session

    @staticmethod
    def _hash_query(query: str) -> str:
        """Create a hash of the normalized query.

        Args:
            query: Query string

        Returns:
            SHA256 hash of normalized query
        """
        normalized = " ".join(query.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize a query for comparison.

        Args:
            query: Raw query string

        Returns:
            Normalized query
        """
        return " ".join(query.lower().split())

    async def record_search(
        self,
        query: str,
        results_count: int,
        took_ms: int = 0,
        entity_types: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        search_syntax: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SearchQuery:
        """Record a search query for analytics.

        Args:
            query: The search query text
            results_count: Number of results returned
            took_ms: Time taken in milliseconds
            entity_types: Entity types searched
            user_id: Optional user identifier
            session_id: Optional session identifier
            search_syntax: Search syntax used (plain, web, phrase)
            metadata: Additional metadata

        Returns:
            Created SearchQuery record
        """
        search = SearchQuery(
            query_text=query,
            query_hash=self._hash_query(query),
            normalized_query=self._normalize_query(query),
            entity_types=entity_types,
            results_count=results_count,
            took_ms=took_ms,
            user_id=user_id,
            session_id=session_id,
            search_syntax=search_syntax,
            context_data=metadata,
        )

        self.session.add(search)
        await self.session.flush()

        return search

    async def record_click(
        self,
        search_id: int,
        clicked_position: int,
        clicked_entity_id: str,
    ) -> None:
        """Record when a user clicks on a search result.

        Args:
            search_id: ID of the search query record
            clicked_position: Position of clicked result (1-indexed)
            clicked_entity_id: ID of the clicked entity
        """
        stmt = (
            select(SearchQuery)
            .where(SearchQuery.id == search_id)
        )
        result = await self.session.execute(stmt)
        search = result.scalar_one_or_none()

        if search:
            search.clicked_result = True
            search.clicked_position = clicked_position
            search.clicked_entity_id = clicked_entity_id
            await self.session.flush()

    async def get_stats(self, days: int = 30) -> SearchStats:
        """Get search statistics for a time period.

        Args:
            days: Number of days to analyze

        Returns:
            SearchStats with aggregate metrics
        """
        since = datetime.now(UTC) - timedelta(days=days)

        # Total searches
        total_stmt = select(func.count()).select_from(SearchQuery).where(
            SearchQuery.created_at >= since
        )
        total_result = await self.session.execute(total_stmt)
        total_searches = total_result.scalar() or 0

        if total_searches == 0:
            return SearchStats()

        # Unique queries
        unique_stmt = select(func.count(func.distinct(SearchQuery.query_hash))).where(
            SearchQuery.created_at >= since
        )
        unique_result = await self.session.execute(unique_stmt)
        unique_queries = unique_result.scalar() or 0

        # Zero result count
        zero_stmt = select(func.count()).select_from(SearchQuery).where(
            SearchQuery.created_at >= since,
            SearchQuery.results_count == 0,
        )
        zero_result = await self.session.execute(zero_stmt)
        zero_count = zero_result.scalar() or 0
        zero_result_rate = zero_count / total_searches if total_searches > 0 else 0.0

        # Average results
        avg_stmt = select(func.avg(SearchQuery.results_count)).where(
            SearchQuery.created_at >= since
        )
        avg_result = await self.session.execute(avg_stmt)
        avg_results = float(avg_result.scalar() or 0)

        # Average response time
        time_stmt = select(func.avg(SearchQuery.took_ms)).where(
            SearchQuery.created_at >= since
        )
        time_result = await self.session.execute(time_stmt)
        avg_time = float(time_result.scalar() or 0)

        # Click-through rate
        clicked_stmt = select(func.count()).select_from(SearchQuery).where(
            SearchQuery.created_at >= since,
            SearchQuery.clicked_result.is_(True),
        )
        clicked_result = await self.session.execute(clicked_stmt)
        clicked_count = clicked_result.scalar() or 0
        ctr = clicked_count / total_searches if total_searches > 0 else 0.0

        # Top queries
        top_stmt = (
            select(
                SearchQuery.normalized_query,
                func.count().label("count"),
                func.avg(SearchQuery.results_count).label("avg_results"),
            )
            .where(SearchQuery.created_at >= since)
            .group_by(SearchQuery.normalized_query)
            .order_by(text("count DESC"))
            .limit(10)
        )
        top_result = await self.session.execute(top_stmt)
        top_queries = [
            {"query": row[0], "count": row[1], "avg_results": float(row[2] or 0)}
            for row in top_result.all()
        ]

        # Zero result queries
        zero_queries_stmt = (
            select(
                SearchQuery.normalized_query,
                func.count().label("count"),
            )
            .where(
                SearchQuery.created_at >= since,
                SearchQuery.results_count == 0,
            )
            .group_by(SearchQuery.normalized_query)
            .order_by(text("count DESC"))
            .limit(10)
        )
        zero_queries_result = await self.session.execute(zero_queries_stmt)
        zero_result_queries = [
            {"query": row[0], "count": row[1]}
            for row in zero_queries_result.all()
        ]

        return SearchStats(
            total_searches=total_searches,
            unique_queries=unique_queries,
            zero_result_rate=zero_result_rate,
            avg_results_count=avg_results,
            avg_response_time_ms=avg_time,
            click_through_rate=ctr,
            top_queries=top_queries,
            zero_result_queries=zero_result_queries,
        )

    async def get_popular_searches(
        self,
        days: int = 7,
        limit: int = 20,
        min_count: int = 2,
    ) -> list[dict[str, Any]]:
        """Get the most popular search queries.

        Args:
            days: Number of days to analyze
            limit: Maximum number of results
            min_count: Minimum occurrences to include

        Returns:
            List of popular queries with counts
        """
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(
                SearchQuery.normalized_query,
                func.count().label("count"),
                func.avg(SearchQuery.results_count).label("avg_results"),
                func.avg(SearchQuery.took_ms).label("avg_time"),
            )
            .where(SearchQuery.created_at >= since)
            .group_by(SearchQuery.normalized_query)
            .having(func.count() >= min_count)
            .order_by(text("count DESC"))
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return [
            {
                "query": row[0],
                "count": row[1],
                "avg_results": float(row[2] or 0),
                "avg_time_ms": float(row[3] or 0),
            }
            for row in result.all()
        ]

    async def get_zero_result_queries(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get queries that returned no results.

        These are opportunities for:
        - Content gaps (missing content users want)
        - Search improvements (better matching/synonyms)
        - Spelling corrections

        Args:
            days: Number of days to analyze
            limit: Maximum number of results

        Returns:
            List of zero-result queries with counts
        """
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(
                SearchQuery.normalized_query,
                func.count().label("count"),
            )
            .where(
                SearchQuery.created_at >= since,
                SearchQuery.results_count == 0,
            )
            .group_by(SearchQuery.normalized_query)
            .order_by(text("count DESC"))
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return [{"query": row[0], "count": row[1]} for row in result.all()]

    async def get_slow_queries(
        self,
        days: int = 7,
        min_time_ms: int = 500,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get slow-performing search queries.

        Args:
            days: Number of days to analyze
            min_time_ms: Minimum response time to include
            limit: Maximum number of results

        Returns:
            List of slow queries with timing info
        """
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(
                SearchQuery.normalized_query,
                func.count().label("count"),
                func.avg(SearchQuery.took_ms).label("avg_time"),
                func.max(SearchQuery.took_ms).label("max_time"),
            )
            .where(
                SearchQuery.created_at >= since,
                SearchQuery.took_ms >= min_time_ms,
            )
            .group_by(SearchQuery.normalized_query)
            .order_by(text("avg_time DESC"))
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return [
            {
                "query": row[0],
                "count": row[1],
                "avg_time_ms": float(row[2] or 0),
                "max_time_ms": row[3],
            }
            for row in result.all()
        ]

    async def generate_insights(self, days: int = 30) -> list[SearchInsight]:
        """Generate actionable search insights.

        Args:
            days: Number of days to analyze

        Returns:
            List of insights and recommendations
        """
        insights = []
        stats = await self.get_stats(days)

        # Zero-result rate insight
        if stats.zero_result_rate > 0.2:
            insights.append(
                SearchInsight(
                    type="warning",
                    title="High Zero-Result Rate",
                    description=f"{stats.zero_result_rate:.1%} of searches return no results",
                    metric="zero_result_rate",
                    value=stats.zero_result_rate,
                    recommendation=(
                        "Review zero-result queries to identify content gaps "
                        "or add synonyms and spelling corrections"
                    ),
                )
            )
        elif stats.zero_result_rate < 0.05:
            insights.append(
                SearchInsight(
                    type="info",
                    title="Excellent Search Coverage",
                    description=f"Only {stats.zero_result_rate:.1%} of searches return no results",
                    metric="zero_result_rate",
                    value=stats.zero_result_rate,
                )
            )

        # Click-through rate insight
        if stats.click_through_rate < 0.3:
            insights.append(
                SearchInsight(
                    type="improvement",
                    title="Low Click-Through Rate",
                    description=f"Only {stats.click_through_rate:.1%} of searches lead to clicks",
                    metric="click_through_rate",
                    value=stats.click_through_rate,
                    recommendation=(
                        "Improve result ranking or snippets to make results "
                        "more relevant and appealing"
                    ),
                )
            )

        # Response time insight
        if stats.avg_response_time_ms > 500:
            insights.append(
                SearchInsight(
                    type="warning",
                    title="Slow Search Response",
                    description=f"Average search takes {stats.avg_response_time_ms:.0f}ms",
                    metric="avg_response_time_ms",
                    value=stats.avg_response_time_ms,
                    recommendation=(
                        "Consider adding more indexes or optimizing "
                        "the search query for better performance"
                    ),
                )
            )

        # Popular queries insight
        if stats.top_queries:
            top_query = stats.top_queries[0]
            insights.append(
                SearchInsight(
                    type="info",
                    title="Most Popular Search",
                    description=f'"{top_query["query"]}" searched {top_query["count"]} times',
                    metric="top_query_count",
                    value=top_query["count"],
                )
            )

        # Zero-result queries needing attention
        if stats.zero_result_queries:
            queries_str = ", ".join(
                f'"{q["query"]}"' for q in stats.zero_result_queries[:3]
            )
            insights.append(
                SearchInsight(
                    type="improvement",
                    title="Content Gaps Detected",
                    description=f"Frequently searched but no results: {queries_str}",
                    recommendation="Consider adding content or synonyms for these terms",
                )
            )

        return insights

    async def get_search_trends(
        self,
        days: int = 30,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Get search volume trends over time.

        Args:
            days: Number of days to analyze
            interval: Grouping interval ("hour", "day", "week")

        Returns:
            List of time periods with search counts
        """
        since = datetime.now(UTC) - timedelta(days=days)

        if interval == "hour":
            trunc_func = func.date_trunc("hour", SearchQuery.created_at)
        elif interval == "week":
            trunc_func = func.date_trunc("week", SearchQuery.created_at)
        else:  # day
            trunc_func = func.date_trunc("day", SearchQuery.created_at)

        stmt = (
            select(
                trunc_func.label("period"),
                func.count().label("count"),
                func.count(func.distinct(SearchQuery.query_hash)).label("unique_queries"),
                func.sum(
                    func.cast(SearchQuery.results_count == 0, Integer)
                ).label("zero_results"),
            )
            .where(SearchQuery.created_at >= since)
            .group_by(text("period"))
            .order_by(text("period"))
        )

        result = await self.session.execute(stmt)
        return [
            {
                "period": row[0].isoformat() if row[0] else None,
                "count": row[1],
                "unique_queries": row[2],
                "zero_results": row[3] or 0,
            }
            for row in result.all()
        ]


__all__ = [
    "SearchQuery",
    "SearchSuggestionLog",
    "SearchStats",
    "SearchInsight",
    "SearchAnalytics",
]
