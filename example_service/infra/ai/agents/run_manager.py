"""Run Manager for AI agent execution tracking.

This module provides comprehensive run management including:
- Run creation and tracking
- Run querying and filtering
- Retry and resume capabilities
- Cost aggregation and reporting
- Run lifecycle management

Example:
    from example_service.infra.ai.agents.run_manager import RunManager

    manager = RunManager(db_session)

    # List runs with filtering
    runs = await manager.list_runs(
        tenant_id="tenant-123",
        status="failed",
        agent_type="research_agent",
    )

    # Retry a failed run
    result = await manager.retry_run(run_id)

    # Resume from checkpoint
    result = await manager.resume_run(run_id, checkpoint_id)

    # Get cost summary
    costs = await manager.get_cost_summary(
        tenant_id="tenant-123",
        start_date=datetime(2024, 1, 1),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.ai.agents.base import AgentResult, BaseAgent
    from example_service.infra.ai.agents.models import AIAgentRun

logger = logging.getLogger(__name__)


@dataclass
class RunFilter:
    """Filter criteria for listing runs."""

    tenant_id: str | None = None
    agent_type: str | None = None
    agent_types: list[str] | None = None
    status: str | None = None
    statuses: list[str] | None = None
    created_by_id: UUID | None = None
    parent_run_id: UUID | None = None
    tags: list[str] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    min_cost_usd: float | None = None
    max_cost_usd: float | None = None
    has_error: bool | None = None
    search_query: str | None = None


@dataclass
class RunListResult:
    """Result from listing runs."""

    runs: list[AIAgentRun]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


@dataclass
class CostSummary:
    """Cost summary for a time period."""

    total_cost_usd: Decimal
    total_runs: int
    successful_runs: int
    failed_runs: int
    total_input_tokens: int
    total_output_tokens: int
    average_cost_per_run: Decimal
    cost_by_agent: dict[str, Decimal] = field(default_factory=dict)
    cost_by_status: dict[str, Decimal] = field(default_factory=dict)
    daily_costs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunStats:
    """Statistics for runs."""

    total_runs: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    cancelled: int = 0
    paused: int = 0
    average_duration_seconds: float | None = None
    success_rate: float | None = None
    average_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))


class RunManager:
    """Manager for AI agent run lifecycle.

    Provides methods for:
    - Creating and tracking runs
    - Querying runs with filters
    - Retrying failed runs
    - Resuming paused runs
    - Cost tracking and reporting
    """

    def __init__(self, db_session: AsyncSession) -> None:
        """Initialize run manager.

        Args:
            db_session: SQLAlchemy async session
        """
        self.db_session = db_session

    async def get_run(
        self,
        run_id: UUID,
        include_steps: bool = False,
        include_messages: bool = False,
        include_checkpoints: bool = False,
    ) -> AIAgentRun | None:
        """Get a run by ID.

        Args:
            run_id: Run UUID
            include_steps: Include step records
            include_messages: Include message history
            include_checkpoints: Include checkpoints

        Returns:
            AIAgentRun if found, None otherwise
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        query = select(AIAgentRun).where(AIAgentRun.id == run_id)

        # Add eager loading options
        options = []
        if include_steps:
            options.append(selectinload(AIAgentRun.steps))
        if include_messages:
            options.append(selectinload(AIAgentRun.messages))
        if include_checkpoints:
            options.append(selectinload(AIAgentRun.checkpoints))

        if options:
            query = query.options(*options)

        result = await self.db_session.execute(query)
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        filter_: RunFilter | None = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> RunListResult:
        """List runs with filtering and pagination.

        Args:
            filter_: Filter criteria
            page: Page number (1-indexed)
            page_size: Items per page
            order_by: Field to order by
            order_desc: Order descending

        Returns:
            RunListResult with runs and pagination info
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        query = select(AIAgentRun)

        # Apply filters
        if filter_:
            conditions = self._build_filter_conditions(filter_)
            if conditions:
                query = query.where(and_(*conditions))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db_session.execute(count_query)
        total_count = total_result.scalar() or 0

        # Apply ordering
        order_column = getattr(AIAgentRun, order_by, AIAgentRun.created_at)
        if order_desc:
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db_session.execute(query)
        runs = list(result.scalars().all())

        return RunListResult(
            runs=runs,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total_count,
            has_prev=page > 1,
        )

    def _build_filter_conditions(self, filter_: RunFilter) -> list[Any]:
        """Build SQLAlchemy filter conditions."""
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = []

        if filter_.tenant_id:
            conditions.append(AIAgentRun.tenant_id == filter_.tenant_id)

        if filter_.agent_type:
            conditions.append(AIAgentRun.agent_type == filter_.agent_type)

        if filter_.agent_types:
            conditions.append(AIAgentRun.agent_type.in_(filter_.agent_types))

        if filter_.status:
            conditions.append(AIAgentRun.status == filter_.status)

        if filter_.statuses:
            conditions.append(AIAgentRun.status.in_(filter_.statuses))

        if filter_.created_by_id:
            conditions.append(AIAgentRun.created_by_id == filter_.created_by_id)

        if filter_.parent_run_id:
            conditions.append(AIAgentRun.parent_run_id == filter_.parent_run_id)

        if filter_.start_date:
            conditions.append(AIAgentRun.created_at >= filter_.start_date)

        if filter_.end_date:
            conditions.append(AIAgentRun.created_at <= filter_.end_date)

        if filter_.min_cost_usd is not None:
            conditions.append(AIAgentRun.total_cost_usd >= filter_.min_cost_usd)

        if filter_.max_cost_usd is not None:
            conditions.append(AIAgentRun.total_cost_usd <= filter_.max_cost_usd)

        if filter_.has_error is not None:
            if filter_.has_error:
                conditions.append(AIAgentRun.error_message.isnot(None))
            else:
                conditions.append(AIAgentRun.error_message.is_(None))

        if filter_.tags:
            # JSON contains check for tags array
            for tag in filter_.tags:
                conditions.append(AIAgentRun.tags.contains([tag]))

        if filter_.search_query:
            search = f"%{filter_.search_query}%"
            conditions.append(
                or_(
                    AIAgentRun.run_name.ilike(search),
                    AIAgentRun.agent_type.ilike(search),
                    AIAgentRun.error_message.ilike(search),
                )
            )

        return conditions

    async def get_stats(
        self,
        tenant_id: str,
        agent_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> RunStats:
        """Get run statistics.

        Args:
            tenant_id: Tenant ID
            agent_type: Optional agent type filter
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            RunStats with aggregated statistics
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [AIAgentRun.tenant_id == tenant_id]

        if agent_type:
            conditions.append(AIAgentRun.agent_type == agent_type)
        if start_date:
            conditions.append(AIAgentRun.created_at >= start_date)
        if end_date:
            conditions.append(AIAgentRun.created_at <= end_date)

        # Get counts by status
        status_query = (
            select(AIAgentRun.status, func.count(AIAgentRun.id))
            .where(and_(*conditions))
            .group_by(AIAgentRun.status)
        )
        status_result = await self.db_session.execute(status_query)
        status_counts = dict(status_result.all())

        # Get aggregates
        agg_query = select(
            func.count(AIAgentRun.id).label("total"),
            func.avg(
                func.extract(
                    "epoch",
                    AIAgentRun.completed_at - AIAgentRun.started_at,
                )
            ).label("avg_duration"),
            func.avg(AIAgentRun.total_cost_usd).label("avg_cost"),
        ).where(and_(*conditions))

        agg_result = await self.db_session.execute(agg_query)
        agg_row = agg_result.one()

        total = agg_row.total or 0
        completed = status_counts.get("completed", 0)
        success_rate = (completed / total * 100) if total > 0 else None

        return RunStats(
            total_runs=total,
            running=status_counts.get("running", 0),
            completed=completed,
            failed=status_counts.get("failed", 0),
            pending=status_counts.get("pending", 0),
            cancelled=status_counts.get("cancelled", 0),
            paused=status_counts.get("paused", 0),
            average_duration_seconds=agg_row.avg_duration,
            success_rate=success_rate,
            average_cost_usd=Decimal(str(agg_row.avg_cost or 0)),
        )

    async def get_cost_summary(
        self,
        tenant_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        group_by_day: bool = True,
    ) -> CostSummary:
        """Get cost summary for a tenant.

        Args:
            tenant_id: Tenant ID
            start_date: Start date for summary
            end_date: End date for summary
            group_by_day: Include daily breakdown

        Returns:
            CostSummary with aggregated cost data
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [AIAgentRun.tenant_id == tenant_id]

        if start_date:
            conditions.append(AIAgentRun.created_at >= start_date)
        if end_date:
            conditions.append(AIAgentRun.created_at <= end_date)

        # Overall aggregates
        agg_query = select(
            func.sum(AIAgentRun.total_cost_usd).label("total_cost"),
            func.count(AIAgentRun.id).label("total_runs"),
            func.sum(AIAgentRun.total_input_tokens).label("input_tokens"),
            func.sum(AIAgentRun.total_output_tokens).label("output_tokens"),
        ).where(and_(*conditions))

        agg_result = await self.db_session.execute(agg_query)
        agg_row = agg_result.one()

        # Counts by status
        status_query = (
            select(
                AIAgentRun.status,
                func.count(AIAgentRun.id).label("count"),
                func.sum(AIAgentRun.total_cost_usd).label("cost"),
            )
            .where(and_(*conditions))
            .group_by(AIAgentRun.status)
        )
        status_result = await self.db_session.execute(status_query)
        status_rows = status_result.all()

        successful = 0
        failed = 0
        cost_by_status: dict[str, Decimal] = {}
        for row in status_rows:
            cost_by_status[row.status] = Decimal(str(row.cost or 0))
            if row.status == "completed":
                successful = row.count
            elif row.status == "failed":
                failed = row.count

        # Cost by agent type
        agent_query = (
            select(
                AIAgentRun.agent_type,
                func.sum(AIAgentRun.total_cost_usd).label("cost"),
            )
            .where(and_(*conditions))
            .group_by(AIAgentRun.agent_type)
        )
        agent_result = await self.db_session.execute(agent_query)
        cost_by_agent = {
            row.agent_type: Decimal(str(row.cost or 0))
            for row in agent_result.all()
        }

        # Daily breakdown
        daily_costs: list[dict[str, Any]] = []
        if group_by_day:
            daily_query = (
                select(
                    func.date(AIAgentRun.created_at).label("date"),
                    func.sum(AIAgentRun.total_cost_usd).label("cost"),
                    func.count(AIAgentRun.id).label("runs"),
                )
                .where(and_(*conditions))
                .group_by(func.date(AIAgentRun.created_at))
                .order_by(func.date(AIAgentRun.created_at))
            )
            daily_result = await self.db_session.execute(daily_query)
            daily_costs = [
                {
                    "date": str(row.date),
                    "cost_usd": float(row.cost or 0),
                    "runs": row.runs,
                }
                for row in daily_result.all()
            ]

        total_cost = Decimal(str(agg_row.total_cost or 0))
        total_runs = agg_row.total_runs or 0

        return CostSummary(
            total_cost_usd=total_cost,
            total_runs=total_runs,
            successful_runs=successful,
            failed_runs=failed,
            total_input_tokens=agg_row.input_tokens or 0,
            total_output_tokens=agg_row.output_tokens or 0,
            average_cost_per_run=(
                total_cost / total_runs if total_runs > 0 else Decimal("0")
            ),
            cost_by_agent=cost_by_agent,
            cost_by_status=cost_by_status,
            daily_costs=daily_costs,
        )

    async def retry_run(
        self,
        run_id: UUID,
        agent_factory: callable[[Any], BaseAgent[Any, Any]],
        max_additional_retries: int | None = None,
    ) -> AgentResult[Any]:
        """Retry a failed run.

        Creates a new run with the same input as the failed run.

        Args:
            run_id: ID of the run to retry
            agent_factory: Factory function to create agent instance
            max_additional_retries: Override max retries

        Returns:
            AgentResult from the retry
        """
        original_run = await self.get_run(run_id)
        if not original_run:
            raise ValueError(f"Run {run_id} not found")

        if original_run.status not in ("failed", "timeout", "cancelled"):
            raise ValueError(f"Run {run_id} is not in a retryable state")

        if original_run.retry_count >= original_run.max_retries:
            if max_additional_retries is None:
                raise ValueError(f"Run {run_id} has exceeded retry limit")

        # Create agent with original config
        agent = agent_factory(original_run.config)

        # Update retry tracking
        original_run.retry_count += 1
        original_run.last_retry_at = datetime.now(UTC)
        await self.db_session.flush()

        # Execute with original input
        result = await agent.execute(
            input_data=original_run.input_data,
            run_name=f"Retry of {original_run.run_name or original_run.id}",
            tags=original_run.tags + ["retry"],
            metadata={
                **original_run.metadata_json,
                "original_run_id": str(run_id),
                "retry_attempt": original_run.retry_count,
            },
        )

        return result

    async def resume_run(
        self,
        run_id: UUID,
        agent_factory: callable[[Any], BaseAgent[Any, Any]],
        checkpoint_id: UUID | None = None,
        human_input: dict[str, Any] | None = None,
    ) -> AgentResult[Any]:
        """Resume a paused run.

        Args:
            run_id: ID of the run to resume
            agent_factory: Factory function to create agent instance
            checkpoint_id: Specific checkpoint to resume from (latest if None)
            human_input: Human input if run was waiting for input

        Returns:
            AgentResult from the resumed execution
        """
        from example_service.infra.ai.agents.models import AIAgentCheckpoint

        original_run = await self.get_run(run_id, include_checkpoints=True)
        if not original_run:
            raise ValueError(f"Run {run_id} not found")

        if original_run.status not in ("paused", "waiting_input"):
            raise ValueError(f"Run {run_id} is not in a resumable state")

        # Get checkpoint
        if checkpoint_id:
            checkpoint = await self.db_session.get(AIAgentCheckpoint, checkpoint_id)
            if not checkpoint or checkpoint.run_id != run_id:
                raise ValueError(f"Checkpoint {checkpoint_id} not found for run")
        else:
            # Get latest valid checkpoint
            checkpoints = [c for c in original_run.checkpoints if c.is_valid]
            if not checkpoints:
                raise ValueError(f"No valid checkpoints found for run {run_id}")
            checkpoint = max(checkpoints, key=lambda c: c.created_at)

        # Create agent
        agent = agent_factory(original_run.config)

        # Update run status
        original_run.status = "running"
        original_run.paused_at = None
        await self.db_session.flush()

        # Execute from checkpoint
        result = await agent.execute(
            input_data=original_run.input_data,
            resume_from_checkpoint=checkpoint.id,
            metadata={
                **original_run.metadata_json,
                "resumed_from_checkpoint": str(checkpoint.id),
                "human_input": human_input,
            },
        )

        return result

    async def cancel_run(self, run_id: UUID, reason: str = "User cancelled") -> bool:
        """Cancel a running or pending run.

        Args:
            run_id: ID of the run to cancel
            reason: Cancellation reason

        Returns:
            True if cancelled, False if not found or not cancellable
        """
        run = await self.get_run(run_id)
        if not run:
            return False

        if run.status not in ("pending", "running", "paused", "waiting_input"):
            return False

        run.status = "cancelled"
        run.error_message = reason
        run.error_code = "cancelled"
        run.completed_at = datetime.now(UTC)
        await self.db_session.flush()

        logger.info(f"Cancelled run {run_id}: {reason}")
        return True

    async def cleanup_stale_runs(
        self,
        tenant_id: str | None = None,
        stale_threshold_hours: int = 24,
        dry_run: bool = True,
    ) -> list[UUID]:
        """Clean up stale running runs.

        Marks runs as failed if they've been running longer than threshold.

        Args:
            tenant_id: Optional tenant filter
            stale_threshold_hours: Hours after which a running run is stale
            dry_run: If True, only return IDs without updating

        Returns:
            List of stale run IDs
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        threshold = datetime.now(UTC) - timedelta(hours=stale_threshold_hours)

        conditions = [
            AIAgentRun.status == "running",
            AIAgentRun.started_at < threshold,
        ]

        if tenant_id:
            conditions.append(AIAgentRun.tenant_id == tenant_id)

        query = select(AIAgentRun).where(and_(*conditions))
        result = await self.db_session.execute(query)
        stale_runs = list(result.scalars().all())

        stale_ids = [run.id for run in stale_runs]

        if not dry_run:
            for run in stale_runs:
                run.status = "failed"
                run.error_message = f"Run timed out (stale after {stale_threshold_hours}h)"
                run.error_code = "stale_timeout"
                run.completed_at = datetime.now(UTC)

            await self.db_session.flush()
            logger.info(f"Cleaned up {len(stale_ids)} stale runs")

        return stale_ids

    async def delete_run(
        self,
        run_id: UUID,
        hard_delete: bool = False,
    ) -> bool:
        """Delete a run.

        Args:
            run_id: ID of the run to delete
            hard_delete: If True, permanently delete; otherwise archive

        Returns:
            True if deleted, False if not found
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        run = await self.get_run(run_id)
        if not run:
            return False

        if hard_delete:
            await self.db_session.delete(run)
        else:
            # Soft delete by adding to metadata
            run.metadata_json["deleted"] = True
            run.metadata_json["deleted_at"] = datetime.now(UTC).isoformat()

        await self.db_session.flush()
        return True

    async def get_recent_runs(
        self,
        tenant_id: str,
        limit: int = 10,
        include_children: bool = False,
    ) -> list[AIAgentRun]:
        """Get recent runs for a tenant.

        Args:
            tenant_id: Tenant ID
            limit: Maximum runs to return
            include_children: Include child runs

        Returns:
            List of recent runs
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [AIAgentRun.tenant_id == tenant_id]

        if not include_children:
            conditions.append(AIAgentRun.parent_run_id.is_(None))

        query = (
            select(AIAgentRun)
            .where(and_(*conditions))
            .order_by(AIAgentRun.created_at.desc())
            .limit(limit)
        )

        result = await self.db_session.execute(query)
        return list(result.scalars().all())

    async def get_run_timeline(
        self,
        run_id: UUID,
    ) -> list[dict[str, Any]]:
        """Get timeline of events for a run.

        Args:
            run_id: Run ID

        Returns:
            List of timeline events
        """
        run = await self.get_run(
            run_id,
            include_steps=True,
            include_messages=True,
            include_checkpoints=True,
        )

        if not run:
            raise ValueError(f"Run {run_id} not found")

        timeline = []

        # Add run creation
        timeline.append({
            "timestamp": run.created_at.isoformat(),
            "type": "run_created",
            "details": {
                "agent_type": run.agent_type,
                "status": "pending",
            },
        })

        # Add run start
        if run.started_at:
            timeline.append({
                "timestamp": run.started_at.isoformat(),
                "type": "run_started",
                "details": {"status": "running"},
            })

        # Add steps
        for step in run.steps:
            if step.started_at:
                timeline.append({
                    "timestamp": step.started_at.isoformat(),
                    "type": "step_started",
                    "details": {
                        "step_name": step.step_name,
                        "step_type": step.step_type,
                        "step_number": step.step_number,
                    },
                })
            if step.completed_at:
                timeline.append({
                    "timestamp": step.completed_at.isoformat(),
                    "type": "step_completed",
                    "details": {
                        "step_name": step.step_name,
                        "status": step.status,
                        "duration_ms": step.duration_ms,
                        "cost_usd": step.cost_usd,
                    },
                })

        # Add checkpoints
        for checkpoint in run.checkpoints:
            timeline.append({
                "timestamp": checkpoint.created_at.isoformat(),
                "type": "checkpoint_created",
                "details": {
                    "checkpoint_name": checkpoint.checkpoint_name,
                    "step_number": checkpoint.step_number,
                },
            })

        # Add run completion
        if run.completed_at:
            timeline.append({
                "timestamp": run.completed_at.isoformat(),
                "type": "run_completed",
                "details": {
                    "status": run.status,
                    "total_cost_usd": run.total_cost_usd,
                    "duration_seconds": run.duration_seconds,
                },
            })

        # Sort by timestamp
        timeline.sort(key=lambda x: x["timestamp"])

        return timeline
