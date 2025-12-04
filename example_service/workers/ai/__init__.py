"""AI processing tasks for Taskiq workers.

Provides background task processing for:
- Pipeline-based AI workflow execution
- Individual step execution
- Scheduled job cleanup

Usage:
    from example_service.workers.ai import execute_pipeline

    # Schedule pipeline execution
    task = await execute_pipeline.kiq(
        pipeline_name="call_analysis",
        input_data={"audio_url": "https://..."},
        tenant_id="tenant-123",
        execution_id="exec-456",
    )

    # Wait for result
    result = await task.wait_result()
"""

from __future__ import annotations

# Import tasks to register them with the broker
# Note: These imports have side effects (task registration)
try:
    from example_service.workers.ai.tasks import (
        AITaskError,
        cleanup_old_ai_jobs,
        execute_pipeline,
        execute_pipeline_step,
    )

    __all__ = [
        "AITaskError",
        "cleanup_old_ai_jobs",
        "execute_pipeline",
        "execute_pipeline_step",
    ]
except ImportError:
    # Tasks may not be available if Taskiq dependencies not installed
    __all__ = []
