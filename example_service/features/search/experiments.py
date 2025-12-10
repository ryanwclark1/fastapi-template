"""A/B testing framework for search experiments.

Provides functionality for running controlled experiments on search features:
- Experiment definition and management
- User assignment to variants
- Metrics tracking and analysis
- Statistical significance calculation

Usage:
    manager = ExperimentManager(session)

    # Create an experiment
    exp = await manager.create_experiment(
        name="click_boost_weight",
        variants={"control": {"weight": 0.1}, "treatment": {"weight": 0.3}},
    )

    # Assign user to variant
    variant = await manager.get_variant("click_boost_weight", user_id="user123")

    # Track conversion
    await manager.track_conversion("click_boost_weight", user_id="user123")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import logging
import math
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ExperimentStatus(StrEnum):
    """Experiment lifecycle status."""

    DRAFT = "draft"  # Not yet started
    RUNNING = "running"  # Actively running
    PAUSED = "paused"  # Temporarily paused
    COMPLETED = "completed"  # Finished
    CANCELLED = "cancelled"  # Cancelled


class SearchExperiment(TimestampedBase):
    """Model for search experiments."""

    __tablename__ = "search_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ExperimentStatus.DRAFT, nullable=False, index=True)
    variants: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    traffic_percentage: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(nullable=True)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hypothesis: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    primary_metric: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experiment_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ExperimentAssignment(TimestampedBase):
    """Model for tracking user assignments to experiments."""

    __tablename__ = "search_experiment_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    experiment_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)


class ExperimentEvent(TimestampedBase):
    """Model for tracking experiment events/conversions."""

    __tablename__ = "search_experiment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    experiment_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


@dataclass
class VariantStats:
    """Statistics for an experiment variant."""

    variant: str
    participants: int
    conversions: int
    conversion_rate: float
    avg_value: float | None
    total_value: float


@dataclass
class ExperimentResults:
    """Results for an experiment."""

    experiment_name: str
    status: str
    start_date: datetime | None
    end_date: datetime | None
    duration_days: int
    total_participants: int
    variants: list[VariantStats]
    winner: str | None
    is_significant: bool
    p_value: float | None
    confidence_level: float
    recommendation: str


@dataclass
class ExperimentConfig:
    """Configuration for running experiments."""

    enabled: bool = True
    default_traffic_percentage: float = 100.0
    min_sample_size: int = 100
    confidence_level: float = 0.95
    auto_stop_on_significance: bool = False


class ExperimentManager:
    """Manager for search A/B experiments.

    Handles experiment lifecycle, user assignment, and metrics tracking.

    Example:
        manager = ExperimentManager(session)

        # Create experiment
        exp = await manager.create_experiment(
            name="new_ranking",
            variants={
                "control": {"algorithm": "default"},
                "treatment": {"algorithm": "boosted"},
            },
            traffic_percentage=50.0,
        )

        # Get user's variant
        variant = await manager.get_variant("new_ranking", user_id)
        config = variant.get("config", {})

        # Track metrics
        await manager.track_event(
            "new_ranking",
            user_id,
            "click",
            value=1.0,
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        config: ExperimentConfig | None = None,
    ) -> None:
        """Initialize the experiment manager.

        Args:
            session: Database session.
            config: Experiment configuration.
        """
        self.session = session
        self.config = config or ExperimentConfig()

    async def create_experiment(
        self,
        name: str,
        variants: dict[str, dict[str, Any]],
        description: str | None = None,
        traffic_percentage: float | None = None,
        hypothesis: str | None = None,
        primary_metric: str | None = None,
        owner: str | None = None,
    ) -> SearchExperiment:
        """Create a new experiment.

        Args:
            name: Unique experiment name.
            variants: Dictionary of variant names to configurations.
            description: Experiment description.
            traffic_percentage: Percentage of traffic to include.
            hypothesis: What we're testing.
            primary_metric: Main success metric.
            owner: Experiment owner.

        Returns:
            Created experiment.
        """
        # Ensure at least 2 variants
        if len(variants) < 2:
            raise ValueError("Experiment must have at least 2 variants")

        # Ensure "control" variant exists
        if "control" not in variants:
            logger.warning("Experiment '%s' has no 'control' variant", name)

        experiment = SearchExperiment(
            name=name,
            description=description,
            status=ExperimentStatus.DRAFT,
            variants=variants,
            traffic_percentage=traffic_percentage or self.config.default_traffic_percentage,
            hypothesis=hypothesis,
            primary_metric=primary_metric or "click_rate",
            owner=owner,
        )

        self.session.add(experiment)
        await self.session.flush()

        logger.info("Created experiment: %s with variants: %s", name, list(variants.keys()))
        return experiment

    async def start_experiment(self, name: str) -> SearchExperiment | None:
        """Start an experiment.

        Args:
            name: Experiment name.

        Returns:
            Updated experiment or None.
        """
        experiment = await self._get_experiment(name)
        if not experiment:
            return None

        if experiment.status not in (ExperimentStatus.DRAFT, ExperimentStatus.PAUSED):
            logger.warning("Cannot start experiment '%s' in status '%s'", name, experiment.status)
            return experiment

        experiment.status = ExperimentStatus.RUNNING
        experiment.start_date = datetime.now(UTC)
        await self.session.flush()

        logger.info("Started experiment: %s", name)
        return experiment

    async def stop_experiment(self, name: str) -> SearchExperiment | None:
        """Stop/complete an experiment.

        Args:
            name: Experiment name.

        Returns:
            Updated experiment or None.
        """
        experiment = await self._get_experiment(name)
        if not experiment:
            return None

        experiment.status = ExperimentStatus.COMPLETED
        experiment.end_date = datetime.now(UTC)
        await self.session.flush()

        logger.info("Stopped experiment: %s", name)
        return experiment

    async def get_variant(
        self,
        experiment_name: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Get the variant for a user in an experiment.

        Assigns user to variant if not already assigned.

        Args:
            experiment_name: Experiment name.
            user_id: User identifier.

        Returns:
            Variant configuration or None if not in experiment.
        """
        if not self.config.enabled:
            return None

        experiment = await self._get_experiment(experiment_name)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None

        # Check if user is already assigned
        stmt = select(ExperimentAssignment).where(
            ExperimentAssignment.experiment_name == experiment_name,
            ExperimentAssignment.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        assignment = result.scalar_one_or_none()

        if assignment:
            variant_name = assignment.variant
        else:
            # Check traffic allocation
            if not self._is_in_traffic(user_id, experiment.traffic_percentage):
                return None

            # Assign to variant
            variant_name = self._assign_variant(user_id, experiment_name, list(experiment.variants.keys()))

            # Record assignment
            assignment = ExperimentAssignment(
                experiment_id=experiment.id,
                experiment_name=experiment_name,
                user_id=user_id,
                variant=variant_name,
            )
            self.session.add(assignment)
            await self.session.flush()

        # Return variant config
        return {
            "variant": variant_name,
            "config": experiment.variants.get(variant_name, {}),
            "experiment": experiment_name,
        }

    async def track_event(
        self,
        experiment_name: str,
        user_id: str,
        event_type: str,
        value: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Track an event for an experiment.

        Args:
            experiment_name: Experiment name.
            user_id: User identifier.
            event_type: Type of event (e.g., "click", "conversion").
            value: Optional numeric value.
            metadata: Additional event data.

        Returns:
            True if event was tracked.
        """
        # Get user's assignment
        stmt = select(ExperimentAssignment).where(
            ExperimentAssignment.experiment_name == experiment_name,
            ExperimentAssignment.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        assignment = result.scalar_one_or_none()

        if not assignment:
            return False

        event = ExperimentEvent(
            experiment_id=assignment.experiment_id,
            experiment_name=experiment_name,
            user_id=user_id,
            variant=assignment.variant,
            event_type=event_type,
            event_value=value,
            event_data=metadata,
        )

        self.session.add(event)
        await self.session.flush()
        return True

    async def get_results(
        self,
        experiment_name: str,
    ) -> ExperimentResults | None:
        """Get experiment results with statistical analysis.

        Args:
            experiment_name: Experiment name.

        Returns:
            ExperimentResults or None.
        """
        experiment = await self._get_experiment(experiment_name)
        if not experiment:
            return None

        variants = list(experiment.variants.keys())
        variant_stats = []

        for variant in variants:
            stats = await self._get_variant_stats(experiment_name, variant)
            variant_stats.append(stats)

        # Calculate duration
        duration_days = 0
        if experiment.start_date:
            end = experiment.end_date or datetime.now(UTC)
            duration_days = (end - experiment.start_date).days

        # Determine winner and significance
        winner = None
        is_significant = False
        p_value = None

        if len(variant_stats) >= 2:
            # Simple comparison between control and first treatment
            control = next((v for v in variant_stats if v.variant == "control"), variant_stats[0])
            treatment = next((v for v in variant_stats if v.variant != "control"), variant_stats[1])

            # Check if we have enough data
            if control.participants >= self.config.min_sample_size and treatment.participants >= self.config.min_sample_size:
                p_value = self._calculate_p_value(control, treatment)
                is_significant = p_value < (1 - self.config.confidence_level)

                if is_significant:
                    winner = treatment.variant if treatment.conversion_rate > control.conversion_rate else control.variant

        # Generate recommendation
        recommendation = self._generate_recommendation(
            variant_stats,
            winner,
            is_significant,
            experiment.status,
        )

        return ExperimentResults(
            experiment_name=experiment_name,
            status=experiment.status,
            start_date=experiment.start_date,
            end_date=experiment.end_date,
            duration_days=duration_days,
            total_participants=sum(v.participants for v in variant_stats),
            variants=variant_stats,
            winner=winner,
            is_significant=is_significant,
            p_value=p_value,
            confidence_level=self.config.confidence_level,
            recommendation=recommendation,
        )

    async def _get_experiment(self, name: str) -> SearchExperiment | None:
        """Get an experiment by name."""
        stmt = select(SearchExperiment).where(SearchExperiment.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_variant_stats(
        self,
        experiment_name: str,
        variant: str,
    ) -> VariantStats:
        """Get statistics for a variant."""
        # Count participants
        participants_stmt = select(func.count()).select_from(ExperimentAssignment).where(
            ExperimentAssignment.experiment_name == experiment_name,
            ExperimentAssignment.variant == variant,
        )
        participants_result = await self.session.execute(participants_stmt)
        participants = participants_result.scalar() or 0

        # Count conversions (assuming "click" or "conversion" event types)
        conversions_stmt = select(
            func.count(func.distinct(ExperimentEvent.user_id)),
            func.avg(ExperimentEvent.event_value),
            func.sum(ExperimentEvent.event_value),
        ).where(
            ExperimentEvent.experiment_name == experiment_name,
            ExperimentEvent.variant == variant,
            ExperimentEvent.event_type.in_(["click", "conversion"]),
        )
        conversions_result = await self.session.execute(conversions_stmt)
        row = conversions_result.first()

        conversions = row[0] if row else 0
        avg_value = float(row[1]) if row and row[1] else None
        total_value = float(row[2]) if row and row[2] else 0.0

        conversion_rate = conversions / participants if participants > 0 else 0.0

        return VariantStats(
            variant=variant,
            participants=participants,
            conversions=conversions,
            conversion_rate=conversion_rate,
            avg_value=avg_value,
            total_value=total_value,
        )

    def _is_in_traffic(self, user_id: str, traffic_percentage: float) -> bool:
        """Check if user is in the traffic allocation."""
        if traffic_percentage >= 100.0:
            return True

        hash_value = int(hashlib.md5(user_id.encode()).hexdigest()[:8], 16)  # noqa: S324
        bucket = (hash_value % 100) + 1
        return bucket <= traffic_percentage

    def _assign_variant(
        self,
        user_id: str,
        experiment_name: str,
        variants: list[str],
    ) -> str:
        """Deterministically assign user to a variant."""
        # Use hash for consistent assignment
        key = f"{experiment_name}:{user_id}"
        hash_value = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)  # noqa: S324
        index = hash_value % len(variants)
        return variants[index]

    def _calculate_p_value(
        self,
        control: VariantStats,
        treatment: VariantStats,
    ) -> float:
        """Calculate p-value using two-proportion z-test."""
        # Pool the proportions
        n1 = control.participants
        n2 = treatment.participants
        x1 = control.conversions
        x2 = treatment.conversions

        p1 = x1 / n1 if n1 > 0 else 0
        p2 = x2 / n2 if n2 > 0 else 0

        # Pooled proportion
        p_pool = (x1 + x2) / (n1 + n2) if (n1 + n2) > 0 else 0

        # Standard error
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if n1 > 0 and n2 > 0 else 0

        if se == 0:
            return 1.0

        # Z-score
        z = abs(p1 - p2) / se

        # Approximate p-value using normal distribution
        # Using simplified approximation
        p_value = 2 * (1 - self._normal_cdf(z))

        return p_value

    def _normal_cdf(self, x: float) -> float:
        """Approximate normal CDF."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def _generate_recommendation(
        self,
        variants: list[VariantStats],
        winner: str | None,
        is_significant: bool,
        status: str,
    ) -> str:
        """Generate a recommendation based on results."""
        if status == ExperimentStatus.DRAFT:
            return "Experiment not yet started. Start the experiment to begin collecting data."

        total_participants = sum(v.participants for v in variants)
        if total_participants < self.config.min_sample_size * len(variants):
            needed = self.config.min_sample_size * len(variants) - total_participants
            return f"Need more data. Collect {needed} more participants for reliable results."

        if is_significant and winner:
            return f"Significant result! '{winner}' variant is the winner. Consider rolling out."

        if not is_significant:
            return "No significant difference detected. Continue running or consider ending if sufficient data."

        return "Review results and make a decision based on business context."


__all__ = [
    "ExperimentAssignment",
    "ExperimentConfig",
    "ExperimentEvent",
    "ExperimentManager",
    "ExperimentResults",
    "ExperimentStatus",
    "SearchExperiment",
    "VariantStats",
]
