"""AI processing tasks for background execution.

This module provides Taskiq tasks for:
- Pipeline execution (transcription, analysis, coaching)
- Batch job execution
- Heavy AI operations that shouldn't block the API
- Scheduled cleanup of old jobs
"""

from __future__ import annotations

import logging
from typing import Any

from example_service.infra.database.session import get_async_session
from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)


class AITaskError(Exception):
    """AI task operation error."""



if broker is not None:

    # =========================================================================
    # Pipeline-Based Tasks (using InstrumentedOrchestrator)
    # =========================================================================

    @broker.task(retry_on_error=True, max_retries=2)
    async def execute_pipeline(
        pipeline_name: str,
        input_data: dict[str, Any],
        tenant_id: str,
        execution_id: str,
        options: dict[str, Any] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        """Execute an AI pipeline in background.

        This task uses the InstrumentedOrchestrator with:
        - Capability-based provider discovery
        - Automatic fallbacks
        - Real-time event emission
        - Full cost tracking

        Args:
            pipeline_name: Name of predefined pipeline (call_analysis, transcription, etc.)
            input_data: Input data for the pipeline
            tenant_id: Tenant identifier
            execution_id: Unique execution ID for tracking
            options: Optional pipeline options

        Returns:
            Pipeline result with all outputs and metrics

        Raises:
            AITaskError: If pipeline execution fails

        Example:
            from example_service.workers.ai import execute_pipeline

            task = await execute_pipeline.kiq(
                pipeline_name="call_analysis",
                input_data={"audio_url": "https://..."},
                tenant_id="tenant-123",
                execution_id="exec-456",
            )
            result = await task.wait_result()
        """
        logger.info(
            "Starting pipeline execution task",
            extra={
                "pipeline_name": pipeline_name,
                "execution_id": execution_id,
                "tenant_id": tenant_id,
            },
        )

        try:
            from example_service.infra.ai import (
                get_instrumented_orchestrator,
                get_pipeline,
            )

            # Get pipeline definition
            pipeline = get_pipeline(pipeline_name)
            if pipeline is None:
                raise AITaskError(f"Pipeline '{pipeline_name}' not found")

            # Get orchestrator
            orchestrator = get_instrumented_orchestrator()

            # Execute pipeline
            result = await orchestrator.execute(
                pipeline=pipeline,
                input_data=input_data,
                tenant_id=tenant_id,
                budget_limit_usd=None,
            )

            # Convert to serializable dict
            result_dict = {
                "execution_id": result.execution_id,
                "pipeline_name": result.pipeline_name,
                "pipeline_version": result.pipeline_version,
                "success": result.success,
                "output": result.output,
                "completed_steps": result.completed_steps,
                "failed_step": result.failed_step,
                "total_duration_ms": result.total_duration_ms,
                "total_cost_usd": str(result.total_cost_usd),
                "compensation_performed": result.compensation_performed,
                "compensated_steps": result.compensated_steps,
                "error": result.error,
            }

            logger.info(
                "Pipeline execution task completed",
                extra={
                    "pipeline_name": pipeline_name,
                    "execution_id": execution_id,
                    "success": result.success,
                    "duration_ms": result.total_duration_ms,
                    "cost_usd": str(result.total_cost_usd),
                },
            )

            return result_dict

        except AITaskError:
            raise
        except Exception as e:
            logger.error(
                "Pipeline execution task failed",
                extra={
                    "pipeline_name": pipeline_name,
                    "execution_id": execution_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise AITaskError(f"Pipeline execution failed: {e}") from e

    @broker.task()
    async def execute_pipeline_step(
        pipeline_name: str,
        step_name: str,
        input_data: dict[str, Any],
        tenant_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single pipeline step in background.

        Useful for fine-grained control or step-by-step execution.

        Args:
            pipeline_name: Name of the pipeline containing the step
            step_name: Name of the step to execute
            input_data: Input data for the step
            tenant_id: Tenant identifier
            context: Optional execution context from previous steps

        Returns:
            Step result with output and metrics
        """
        logger.info(
            "Starting pipeline step task",
            extra={
                "pipeline_name": pipeline_name,
                "step_name": step_name,
                "tenant_id": tenant_id,
            },
        )

        try:
            from example_service.infra.ai import get_pipeline
            from example_service.infra.ai.pipelines import PipelineExecutor

            # Get pipeline definition
            pipeline = get_pipeline(pipeline_name)
            if pipeline is None:
                raise AITaskError(f"Pipeline '{pipeline_name}' not found")

            # Find the step
            step = pipeline.get_step(step_name)
            if step is None:
                raise AITaskError(f"Step '{step_name}' not found in pipeline '{pipeline_name}'")

            # Create executor and run step
            from example_service.infra.ai.pipelines.types import PipelineContext

            executor = PipelineExecutor()
            # Create PipelineContext from dict context
            pipeline_context = PipelineContext(
                pipeline_name=pipeline_name,
                tenant_id=tenant_id,
                data=context or {},
                initial_input=input_data or {},
            )

            step_result = await executor._execute_step(
                step=step,
                context=pipeline_context,
                api_keys={},
                models={},
            )

            result_dict = {
                "step_name": step_result.step_name,
                "status": step_result.status.value,
                "output": step_result.operation_result.data if step_result.operation_result else None,
                "provider_used": step_result.provider_used,
                "duration_ms": step_result.duration_ms,
                "cost_usd": str(step_result.cost_usd),
                "retries": step_result.retries,
                "error": step_result.error,
            }

            logger.info(
                "Pipeline step task completed",
                extra={
                    "pipeline_name": pipeline_name,
                    "step_name": step_name,
                    "status": step_result.status.value,
                },
            )

            return result_dict

        except AITaskError:
            raise
        except Exception as e:
            logger.error(
                "Pipeline step task failed",
                extra={
                    "pipeline_name": pipeline_name,
                    "step_name": step_name,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise AITaskError(f"Pipeline step failed: {e}") from e

    # =========================================================================
    # Maintenance Tasks
    # =========================================================================

    @broker.task()
    async def cleanup_old_ai_jobs(retention_days: int = 30) -> dict[str, Any]:
        """Clean up old AI jobs and usage logs.

        Scheduled task to remove old completed/failed jobs to prevent
        database bloat.

        Args:
            retention_days: Number of days to retain job history

        Returns:
            Cleanup result with counts

        Example:
            # Scheduled to run daily via scheduler
            from example_service.workers.ai import cleanup_old_ai_jobs

            task = await cleanup_old_ai_jobs.kiq(retention_days=30)
            result = await task.wait_result()
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import delete

        from example_service.features.ai.models import AIJob, AIJobStatus, AIUsageLog

        logger.info("Starting AI job cleanup", extra={"retention_days": retention_days})

        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)

            async with get_async_session() as session:
                # Delete old completed/failed jobs
                job_result = await session.execute(
                    delete(AIJob).where(
                        AIJob.completed_at < cutoff,
                        AIJob.status.in_([AIJobStatus.COMPLETED, AIJobStatus.FAILED]),
                    )
                )
                jobs_deleted = getattr(job_result, "rowcount", 0) or 0

                # Delete old usage logs (orphaned or just old)
                usage_result = await session.execute(
                    delete(AIUsageLog).where(AIUsageLog.created_at < cutoff)
                )
                logs_deleted = getattr(usage_result, "rowcount", 0) or 0

                await session.commit()

            result = {
                "status": "success",
                "jobs_deleted": jobs_deleted,
                "logs_deleted": logs_deleted,
                "retention_days": retention_days,
                "cutoff_date": cutoff.isoformat(),
            }

            logger.info(
                "AI job cleanup completed",
                extra=result,
            )

            return result

        except Exception as e:
            logger.error(
                "AI job cleanup failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise AITaskError(f"Job cleanup failed: {e}") from e
