"""Search result ranking with click signal boosting.

Provides ranking enhancements based on user interaction data:
- Click-through rate boosting
- Position bias correction
- Temporal decay for older clicks
- Entity-specific boost factors

Usage:
    ranker = ClickBoostRanker(session)

    # Get click boost for entity
    boost = await ranker.get_click_boost("posts", "123")

    # Apply boost to ranking
    final_rank = base_rank * (1 + boost * weight)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ClickSignal:
    """Click signal data for an entity."""

    entity_type: str
    entity_id: str
    total_clicks: int
    unique_searches: int
    avg_click_position: float
    last_clicked: datetime | None
    ctr: float  # Click-through rate

    @property
    def click_boost(self) -> float:
        """Calculate click boost factor (0.0 - 1.0)."""
        if self.total_clicks == 0:
            return 0.0

        # Base boost from CTR (normalized)
        ctr_boost = min(self.ctr * 2, 1.0)  # Cap at 1.0

        # Position bonus: items clicked at top positions get less boost
        # (they're already ranking well)
        position_factor = 1.0 / (1.0 + math.log1p(self.avg_click_position))

        # Combine factors
        return ctr_boost * position_factor


@dataclass
class RankingConfig:
    """Configuration for ranking adjustments."""

    # Click boosting
    enable_click_boost: bool = True
    click_boost_weight: float = 0.2  # How much clicks affect ranking (0-1)
    min_clicks_for_boost: int = 3  # Minimum clicks before applying boost
    click_decay_days: int = 30  # Days before clicks start decaying

    # Position bias correction
    enable_position_bias: bool = True
    position_bias_factor: float = 0.1

    # Entity boosting
    entity_boosts: dict[str, float] | None = None

    # Freshness boost
    enable_freshness_boost: bool = False
    freshness_decay_days: int = 7
    freshness_weight: float = 0.1


class ClickBoostRanker:
    """Ranking enhancement using click signals.

    Analyzes click data to boost entities that users frequently click on,
    while accounting for position bias and temporal decay.

    Example:
        ranker = ClickBoostRanker(session)

        # Get boost for ranking
        boost = await ranker.get_click_boost("posts", "123")

        # Apply to search result
        adjusted_rank = base_rank * (1 + boost * 0.2)
    """

    def __init__(
        self,
        session: AsyncSession,
        config: RankingConfig | None = None,
    ) -> None:
        """Initialize the ranker.

        Args:
            session: Database session.
            config: Ranking configuration.
        """
        self.session = session
        self.config = config or RankingConfig()

    async def get_click_signal(
        self,
        entity_type: str,
        entity_id: str,
        days: int | None = None,
    ) -> ClickSignal | None:
        """Get click signal data for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: Entity ID.
            days: Number of days to analyze (default from config).

        Returns:
            ClickSignal data or None.
        """
        from example_service.core.database.search.analytics import SearchQuery

        days = days or self.config.click_decay_days
        since = datetime.now(UTC) - timedelta(days=days)

        # Query click data for this entity
        stmt = select(
            func.count().label("total_clicks"),
            func.count(func.distinct(SearchQuery.query_hash)).label("unique_searches"),
            func.avg(SearchQuery.clicked_position).label("avg_position"),
            func.max(SearchQuery.created_at).label("last_clicked"),
        ).where(
            SearchQuery.clicked_entity_id == entity_id,
            SearchQuery.clicked_result.is_(True),
            SearchQuery.created_at >= since,
        )

        try:
            result = await self.session.execute(stmt)
            row = result.first()

            if not row or row[0] == 0:
                return None

            # Calculate CTR: clicks / impressions for this entity
            # We approximate impressions as unique searches that could have shown this entity
            impressions_stmt = select(func.count(func.distinct(SearchQuery.query_hash))).where(
                SearchQuery.results_count > 0,
                SearchQuery.created_at >= since,
            )
            impressions_result = await self.session.execute(impressions_stmt)
            total_impressions = impressions_result.scalar() or 1

            ctr = row[0] / total_impressions if total_impressions > 0 else 0.0

            return ClickSignal(
                entity_type=entity_type,
                entity_id=entity_id,
                total_clicks=row[0],
                unique_searches=row[1],
                avg_click_position=float(row[2] or 1.0),
                last_clicked=row[3],
                ctr=ctr,
            )
        except Exception as e:
            logger.warning("Failed to get click signal for %s/%s: %s", entity_type, entity_id, e)
            return None

    async def get_click_boost(
        self,
        entity_type: str,
        entity_id: str,
    ) -> float:
        """Get the click boost factor for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: Entity ID.

        Returns:
            Boost factor (0.0 - 1.0).
        """
        if not self.config.enable_click_boost:
            return 0.0

        signal = await self.get_click_signal(entity_type, entity_id)

        if signal is None or signal.total_clicks < self.config.min_clicks_for_boost:
            return 0.0

        # Apply temporal decay
        boost = signal.click_boost
        if signal.last_clicked:
            days_since = (datetime.now(UTC) - signal.last_clicked).days
            decay = math.exp(-days_since / self.config.click_decay_days)
            boost *= decay

        return boost

    async def get_batch_click_boosts(
        self,
        entity_type: str,
        entity_ids: list[str],
    ) -> dict[str, float]:
        """Get click boosts for multiple entities.

        More efficient than calling get_click_boost repeatedly.

        Args:
            entity_type: Type of entity.
            entity_ids: List of entity IDs.

        Returns:
            Dictionary mapping entity ID to boost.
        """
        if not self.config.enable_click_boost or not entity_ids:
            return {}

        from example_service.core.database.search.analytics import SearchQuery

        since = datetime.now(UTC) - timedelta(days=self.config.click_decay_days)

        stmt = (
            select(
                SearchQuery.clicked_entity_id,
                func.count().label("total_clicks"),
                func.avg(SearchQuery.clicked_position).label("avg_position"),
                func.max(SearchQuery.created_at).label("last_clicked"),
            )
            .where(
                SearchQuery.clicked_entity_id.in_(entity_ids),
                SearchQuery.clicked_result.is_(True),
                SearchQuery.created_at >= since,
            )
            .group_by(SearchQuery.clicked_entity_id)
        )

        try:
            result = await self.session.execute(stmt)
            rows = result.all()

            boosts = {}
            for row in rows:
                entity_id = row[0]
                total_clicks = row[1]

                if total_clicks < self.config.min_clicks_for_boost:
                    continue

                # Simple boost calculation
                avg_position = float(row[2] or 1.0)
                last_clicked = row[3]

                # Position factor
                position_factor = 1.0 / (1.0 + math.log1p(avg_position))

                # Base boost from clicks (log scale)
                click_factor = min(math.log1p(total_clicks) / 5.0, 1.0)

                boost = click_factor * position_factor

                # Temporal decay
                if last_clicked:
                    days_since = (datetime.now(UTC) - last_clicked).days
                    decay = math.exp(-days_since / self.config.click_decay_days)
                    boost *= decay

                boosts[entity_id] = boost

            return boosts
        except Exception as e:
            logger.warning("Failed to get batch click boosts: %s", e)
            return {}

    def calculate_final_rank(
        self,
        base_rank: float,
        entity_type: str,
        click_boost: float = 0.0,
        freshness_days: int | None = None,
    ) -> float:
        """Calculate final ranking score with all adjustments.

        Args:
            base_rank: Base FTS ranking score.
            entity_type: Type of entity.
            click_boost: Pre-calculated click boost.
            freshness_days: Days since entity creation (for freshness boost).

        Returns:
            Adjusted ranking score.
        """
        rank = base_rank

        # Apply click boost
        if self.config.enable_click_boost and click_boost > 0:
            rank *= 1 + (click_boost * self.config.click_boost_weight)

        # Apply entity boost
        if self.config.entity_boosts and entity_type in self.config.entity_boosts:
            rank *= self.config.entity_boosts[entity_type]

        # Apply freshness boost
        if self.config.enable_freshness_boost and freshness_days is not None:
            freshness_factor = math.exp(-freshness_days / self.config.freshness_decay_days)
            rank *= 1 + (freshness_factor * self.config.freshness_weight)

        return rank

    async def get_top_clicked_entities(
        self,
        entity_type: str | None = None,
        days: int = 30,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get the most clicked entities.

        Args:
            entity_type: Optional entity type filter.
            days: Number of days to analyze.
            limit: Maximum results.

        Returns:
            List of entities with click stats.
        """
        from example_service.core.database.search.analytics import SearchQuery

        since = datetime.now(UTC) - timedelta(days=days)

        stmt = select(
            SearchQuery.clicked_entity_id,
            func.count().label("total_clicks"),
            func.count(func.distinct(SearchQuery.query_hash)).label("unique_searches"),
            func.avg(SearchQuery.clicked_position).label("avg_position"),
        ).where(
            SearchQuery.clicked_result.is_(True),
            SearchQuery.created_at >= since,
        )

        # Note: entity_type would need to be stored in SearchQuery
        # For now, we return all clicked entities

        stmt = stmt.group_by(SearchQuery.clicked_entity_id).order_by(text("total_clicks DESC")).limit(limit)

        try:
            result = await self.session.execute(stmt)
            return [
                {
                    "entity_id": row[0],
                    "total_clicks": row[1],
                    "unique_searches": row[2],
                    "avg_position": float(row[3] or 0),
                }
                for row in result.all()
            ]
        except Exception as e:
            logger.warning("Failed to get top clicked entities: %s", e)
            return []


__all__ = [
    "ClickBoostRanker",
    "ClickSignal",
    "RankingConfig",
]
