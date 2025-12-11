"""Pipeline Executor with fallback chains and saga compensation.

This module executes pipeline definitions with:
- Provider fallback chains for resilience
- Retry logic with exponential backoff
- Timeout handling
- Saga pattern compensation on failure
- Fine-grained progress tracking
- Cost aggregation

Architecture:
    PipelineExecutor
        ├── execute_pipeline() - Main entry point
        ├── _execute_step() - Single step execution
        ├── _execute_with_fallback() - Try providers in order
        ├── _execute_with_retry() - Retry on failure
        └── _run_compensation() - Saga rollback

Example:
    from example_service.infra.ai.pipelines.executor import PipelineExecutor
    from example_service.infra.ai.capabilities import get_capability_registry

    executor = PipelineExecutor(
        registry=get_capability_registry(),
        progress_callback=update_job_progress,
    )

    result = await executor.execute(
        pipeline=my_pipeline,
        input_data={"audio": audio_bytes},
        tenant_id="tenant-123",
    )

    if result.success:
        print(f"Complete! Cost: ${result.total_cost_usd}")
    else:
        print(f"Failed at {result.failed_step}: {result.error}")
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.capabilities.registry import (
    CapabilityRegistry,
    get_capability_registry,
)
from example_service.infra.ai.capabilities.types import OperationResult
from example_service.infra.ai.pipelines.types import (
    PipelineContext,
    PipelineDefinition,
    PipelineResult,
    PipelineStep,
    ProgressCallback,
    StepResult,
    StepStatus,
)

if TYPE_CHECKING:
    from example_service.infra.ai.capabilities.adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)


class PipelineExecutionError(Exception):
    """Raised when pipeline execution fails."""

    def __init__(
        self,
        message: str,
        step_name: str | None = None,
        error_code: str | None = None,
        context: PipelineContext | None = None,
    ) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.error_code = error_code
        self.context = context


class PipelineExecutor:
    """Executes pipeline definitions with resilience and tracking.

    The executor handles:
    - Building fallback chains from registry
    - Executing steps with retry logic
    - Tracking progress and costs
    - Running saga compensation on failure

    Thread Safety:
        The executor is stateless and safe for concurrent use.
        Each execution gets its own PipelineContext.

    Example:
        executor = PipelineExecutor(
            registry=get_capability_registry(),
            default_api_keys={
                "openai": "sk-...",
                "anthropic": "sk-ant-...",
            },
        )

        result = await executor.execute(
            pipeline=call_analysis_pipeline,
            input_data={"audio_url": "https://..."},
            tenant_id="tenant-123",
        )
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        default_api_keys: dict[str, str] | None = None,
        default_model_overrides: dict[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
        adapter_cache: dict[str, ProviderAdapter] | None = None,
    ) -> None:
        """Initialize executor.

        Args:
            registry: Capability registry (uses global if None)
            default_api_keys: Default API keys by provider name
            default_model_overrides: Default model overrides by provider name
            progress_callback: Callback for progress updates
            adapter_cache: Optional cache for adapter instances
        """
        self.registry = registry or get_capability_registry()
        self.default_api_keys = default_api_keys or {}
        self.default_model_overrides = default_model_overrides or {}
        self.progress_callback = progress_callback
        self._adapter_cache = adapter_cache or {}

    async def execute(
        self,
        pipeline: PipelineDefinition,
        input_data: dict[str, Any],
        *,
        tenant_id: str | None = None,
        api_key_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineResult:
        """Execute a pipeline.

        This is the main entry point for pipeline execution.

        Args:
            pipeline: Pipeline definition to execute
            input_data: Initial input data
            tenant_id: Optional tenant ID for tracking
            api_key_overrides: Provider-specific API key overrides
            model_overrides: Provider-specific model overrides
            progress_callback: Optional progress callback (overrides default)

        Returns:
            PipelineResult with status, output, and metrics
        """
        # Create execution context
        context = PipelineContext(
            pipeline_name=pipeline.name,
            tenant_id=tenant_id,
            initial_input=input_data.copy(),
            started_at=datetime.utcnow(),
        )
        context.data.update(input_data)

        # Merge API keys and model overrides
        api_keys = {**self.default_api_keys, **(api_key_overrides or {})}
        models = {**self.default_model_overrides, **(model_overrides or {})}

        # Use provided callback or default
        callback = progress_callback or self.progress_callback

        logger.info(
            f"Starting pipeline execution: {pipeline.name}",
            extra={
                "execution_id": context.execution_id,
                "pipeline": pipeline.name,
                "version": pipeline.version,
                "tenant_id": tenant_id,
                "step_count": len(pipeline.steps),
            },
        )

        try:
            # Execute all steps
            result = await self._execute_pipeline(
                pipeline=pipeline,
                context=context,
                api_keys=api_keys,
                models=models,
                progress_callback=callback,
            )

            logger.info(
                f"Pipeline execution completed: {pipeline.name}",
                extra={
                    "execution_id": context.execution_id,
                    "success": result.success,
                    "duration_ms": result.total_duration_ms,
                    "total_cost_usd": str(result.total_cost_usd),
                    "completed_steps": result.completed_steps,
                },
            )

            return result

        except Exception as e:
            logger.exception(
                f"Pipeline execution failed: {pipeline.name}",
                extra={
                    "execution_id": context.execution_id,
                    "error": str(e),
                },
            )

            return PipelineResult(
                execution_id=context.execution_id,
                pipeline_name=pipeline.name,
                pipeline_version=pipeline.version,
                success=False,
                error=str(e),
                completed_steps=context.completed_steps,
                failed_step=context.failed_step,
                output=context.data,
                step_results=context.step_results,
                started_at=context.started_at,
                completed_at=datetime.utcnow(),
            )

    async def _execute_pipeline(
        self,
        pipeline: PipelineDefinition,
        context: PipelineContext,
        api_keys: dict[str, str],
        models: dict[str, str],
        progress_callback: ProgressCallback | None,
    ) -> PipelineResult:
        """Internal pipeline execution loop.

        Executes each step, handling conditions, fallbacks, and compensation.
        """
        total_weight = pipeline.get_total_progress_weight()
        completed_weight = 0.0
        total_cost = Decimal(0)

        try:
            # Execute each step
            for step in pipeline.steps:
                context.current_step = step.name

                # Check condition
                if not step.should_execute(context.data):
                    logger.info(
                        f"Skipping step (condition not met): {step.name}",
                        extra={
                            "execution_id": context.execution_id,
                            "step": step.name,
                        },
                    )
                    context.step_results[step.name] = StepResult(
                        step_name=step.name,
                        status=StepStatus.SKIPPED,
                        skipped_reason="Condition not met",
                    )
                    continue

                # Update progress
                self._update_progress(
                    context,
                    progress_callback,
                    completed_weight / total_weight * 100,
                    f"Running: {step.name}",
                )

                # Execute step
                step_result = await self._execute_step(
                    step=step,
                    context=context,
                    api_keys=api_keys,
                    models=models,
                )

                context.step_results[step.name] = step_result

                if step_result.status == StepStatus.COMPLETED:
                    context.completed_steps.append(step.name)
                    completed_weight += step.progress_weight
                    total_cost += step_result.cost_usd

                    # Store output in context
                    if step_result.operation_result and step_result.operation_result.data:
                        output_key = step.get_output_key()
                        output_data = step_result.operation_result.data

                        # Apply output transform if specified
                        if step.output_transform:
                            output_data = step.output_transform(output_data)

                        context.data[output_key] = output_data

                elif step_result.status == StepStatus.FAILED:
                    if step.continue_on_failure or not step.required:
                        logger.warning(
                            f"Step failed but continuing: {step.name}",
                            extra={
                                "execution_id": context.execution_id,
                                "step": step.name,
                                "error": step_result.error,
                            },
                        )
                        completed_weight += step.progress_weight
                    else:
                        # Step failed and is required - trigger compensation
                        context.failed_step = step.name
                        context.failure_error = step_result.error

                        if pipeline.enable_compensation:
                            await self._run_compensation(
                                pipeline=pipeline,
                                context=context,
                                progress_callback=progress_callback,
                            )

                        # Fail fast or continue based on config
                        if pipeline.fail_fast:
                            return self._create_failure_result(
                                pipeline=pipeline,
                                context=context,
                                total_cost=total_cost,
                            )

            # All steps completed
            self._update_progress(
                context,
                progress_callback,
                100.0,
                "Complete",
            )

            return PipelineResult(
                execution_id=context.execution_id,
                pipeline_name=pipeline.name,
                pipeline_version=pipeline.version,
                success=True,
                completed_steps=context.completed_steps,
                output=context.data,
                step_results=context.step_results,
                total_cost_usd=total_cost,
                total_duration_ms=(
                    datetime.utcnow() - context.started_at
                ).total_seconds() * 1000 if context.started_at else 0,
                started_at=context.started_at,
                completed_at=datetime.utcnow(),
            )

        except TimeoutError:
            context.failed_step = context.current_step
            context.failure_error = f"Pipeline timed out after {pipeline.timeout_seconds}s"

            if pipeline.enable_compensation:
                await self._run_compensation(
                    pipeline=pipeline,
                    context=context,
                    progress_callback=progress_callback,
                )

            return self._create_failure_result(
                pipeline=pipeline,
                context=context,
                total_cost=total_cost,
                error="Pipeline execution timed out",
            )

    async def _execute_step(
        self,
        step: PipelineStep,
        context: PipelineContext,
        api_keys: dict[str, str],
        models: dict[str, str],
    ) -> StepResult:
        """Execute a single pipeline step.

        Handles fallback chains and retry logic.
        """
        started_at = datetime.utcnow()
        fallbacks_attempted: list[str] = []

        # Build fallback chain
        fallback_chain = self._build_fallback_chain(step)

        if not fallback_chain:
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                error=f"No providers available for capability: {step.capability}",
                error_code="NO_PROVIDERS",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        # Get input data
        input_data = step.get_input(context.data)

        # Try each provider in fallback chain
        last_error: str | None = None
        last_error_code: str | None = None

        for provider_name in fallback_chain:
            try:
                # Get or create adapter
                adapter = self._get_adapter(
                    provider_name=provider_name,
                    api_key=api_keys.get(provider_name),
                    model_name=models.get(provider_name),
                )

                # Execute with retry
                result = await self._execute_with_retry(
                    adapter=adapter,
                    step=step,
                    input_data=input_data,
                )

                if result.success:
                    return StepResult(
                        step_name=step.name,
                        status=StepStatus.COMPLETED,
                        operation_result=result,
                        provider_used=provider_name,
                        fallbacks_attempted=fallbacks_attempted,
                        started_at=started_at,
                        completed_at=datetime.utcnow(),
                    )

                # Provider failed, try next
                fallbacks_attempted.append(provider_name)
                last_error = result.error
                last_error_code = result.error_code

                logger.warning(
                    f"Provider failed, trying fallback: {provider_name}",
                    extra={
                        "execution_id": context.execution_id,
                        "step": step.name,
                        "provider": provider_name,
                        "error": result.error,
                    },
                )

            except Exception as e:
                fallbacks_attempted.append(provider_name)
                last_error = str(e)

                logger.exception(
                    f"Provider exception, trying fallback: {provider_name}",
                    extra={
                        "execution_id": context.execution_id,
                        "step": step.name,
                        "provider": provider_name,
                    },
                )

        # All providers failed
        return StepResult(
            step_name=step.name,
            status=StepStatus.FAILED,
            error=last_error or "All providers failed",
            error_code=last_error_code,
            fallbacks_attempted=fallbacks_attempted,
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _execute_with_retry(
        self,
        adapter: ProviderAdapter,
        step: PipelineStep,
        input_data: Any,
    ) -> OperationResult:
        """Execute step with retry logic.

        Implements exponential backoff retry.
        """
        policy = step.retry_policy
        last_result: OperationResult | None = None

        for attempt in range(1, policy.max_attempts + 1):
            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    adapter.execute(
                        capability=step.capability,
                        input_data=input_data,
                        **step.options,
                    ),
                    timeout=step.timeout_seconds,
                )

                last_result = result

                if result.success:
                    return result

                # Check if error is retryable
                if not result.retryable:
                    return result

                if policy.retryable_errors and result.error_code not in policy.retryable_errors:
                    return result

            except TimeoutError:
                last_result = OperationResult(
                    success=False,
                    data=None,
                    provider_name=adapter.provider_name,
                    capability=step.capability,
                    error=f"Timeout after {step.timeout_seconds}s",
                    error_code="TIMEOUT",
                    retryable=True,
                )

            except Exception as e:
                last_result = OperationResult(
                    success=False,
                    data=None,
                    provider_name=adapter.provider_name,
                    capability=step.capability,
                    error=str(e),
                    error_code="EXCEPTION",
                    retryable=True,
                )

            # Wait before retry (if not last attempt)
            if attempt < policy.max_attempts:
                delay_ms = policy.get_delay_ms(attempt)
                await asyncio.sleep(delay_ms / 1000)

        return last_result or OperationResult(
            success=False,
            data=None,
            provider_name=adapter.provider_name,
            capability=step.capability,
            error="Max retries exceeded",
            error_code="MAX_RETRIES",
            retryable=False,
        )

    def _build_fallback_chain(self, step: PipelineStep) -> list[str]:
        """Build provider fallback chain for a step.

        Uses step preferences and registry to build chain.
        """
        if not step.fallback_config.enabled:
            # No fallback - use first preferred provider or best available
            if step.provider_preference:
                return step.provider_preference[:1]
            providers = self.registry.get_providers_for_capability(step.capability)
            return [providers[0].provider_name] if providers else []

        # Build chain from registry
        return self.registry.build_fallback_chain(
            capability=step.capability,
            primary_provider=step.provider_preference[0] if step.provider_preference else None,
            max_fallbacks=step.fallback_config.max_fallbacks,
            exclude_providers=step.fallback_config.excluded_providers,
            prefer_same_quality=step.fallback_config.prefer_same_quality,
        )


    def _get_adapter(
        self,
        provider_name: str,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> ProviderAdapter:
        """Get or create an adapter instance.

        Uses cache for efficiency.
        """
        cache_key = f"{provider_name}:{api_key or ''}:{model_name or ''}"

        if cache_key not in self._adapter_cache:
            adapter = self.registry.create_adapter(
                provider_name=provider_name,
                api_key=api_key,
                model_name=model_name,
            )
            self._adapter_cache[cache_key] = adapter

        return self._adapter_cache[cache_key]

    async def _run_compensation(
        self,
        pipeline: PipelineDefinition,
        context: PipelineContext,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Run saga compensation for completed steps.

        Executes compensation in reverse order.
        """
        logger.info(
            f"Starting compensation for pipeline: {pipeline.name}",
            extra={
                "execution_id": context.execution_id,
                "completed_steps": context.completed_steps,
            },
        )

        self._update_progress(
            context,
            progress_callback,
            context.progress_percent,
            "Running compensation...",
        )

        # Run compensation in reverse order
        for step_name in reversed(context.completed_steps):
            step = pipeline.get_step(step_name)
            if not step or not step.compensation:
                continue

            try:
                success = await asyncio.wait_for(
                    step.compensation.execute(context.data),
                    timeout=step.compensation.timeout_seconds,
                )

                if success:
                    context.compensated_steps.append(step_name)
                    logger.info(
                        f"Compensation succeeded: {step_name}",
                        extra={
                            "execution_id": context.execution_id,
                            "step": step_name,
                        },
                    )
                else:
                    error_msg = f"Compensation failed: {step_name}"
                    context.compensation_errors.append(error_msg)
                    logger.error(
                        error_msg,
                        extra={"execution_id": context.execution_id},
                    )

            except TimeoutError:
                error_msg = f"Compensation timed out: {step_name}"
                context.compensation_errors.append(error_msg)
                logger.exception(
                    error_msg,
                    extra={
                        "execution_id": context.execution_id,
                        "timeout": step.compensation.timeout_seconds,
                    },
                )

            except Exception as e:
                error_msg = f"Compensation exception for {step_name}: {e}"
                context.compensation_errors.append(error_msg)
                logger.exception(
                    error_msg,
                    extra={"execution_id": context.execution_id},
                )

    def _create_failure_result(
        self,
        pipeline: PipelineDefinition,
        context: PipelineContext,
        total_cost: Decimal,
        error: str | None = None,
    ) -> PipelineResult:
        """Create a failure result."""
        return PipelineResult(
            execution_id=context.execution_id,
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.version,
            success=False,
            completed_steps=context.completed_steps,
            failed_step=context.failed_step,
            error=error or context.failure_error,
            output=context.data,
            step_results=context.step_results,
            total_cost_usd=total_cost,
            total_duration_ms=(
                datetime.utcnow() - context.started_at
            ).total_seconds() * 1000 if context.started_at else 0,
            started_at=context.started_at,
            completed_at=datetime.utcnow(),
            compensation_performed=bool(context.compensated_steps),
            compensated_steps=context.compensated_steps,
        )

    def _update_progress(
        self,
        context: PipelineContext,
        callback: ProgressCallback | None,
        percent: float,
        message: str,
    ) -> None:
        """Update progress and invoke callback."""
        context.set_progress(percent, message)

        if callback:
            try:
                callback(context.execution_id, percent, message)
            except Exception as e:
                logger.warning(
                    f"Progress callback failed: {e}",
                    extra={"execution_id": context.execution_id},
                )


class PipelineExecutorFactory:
    """Factory for creating configured pipeline executors.

    Use this to create executors with consistent configuration.

    Example:
        factory = PipelineExecutorFactory(
            registry=get_capability_registry(),
            default_api_keys=settings.ai_api_keys,
        )

        executor = factory.create()
        result = await executor.execute(pipeline, input_data)
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        default_api_keys: dict[str, str] | None = None,
        default_model_overrides: dict[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize factory.

        Args:
            registry: Capability registry to use
            default_api_keys: Default API keys
            default_model_overrides: Default model overrides
            progress_callback: Default progress callback
        """
        self.registry = registry or get_capability_registry()
        self.default_api_keys = default_api_keys or {}
        self.default_model_overrides = default_model_overrides or {}
        self.progress_callback = progress_callback

    def create(
        self,
        api_keys: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineExecutor:
        """Create a new executor instance.

        Args:
            api_keys: Override API keys
            model_overrides: Override model names
            progress_callback: Override progress callback

        Returns:
            Configured PipelineExecutor
        """
        return PipelineExecutor(
            registry=self.registry,
            default_api_keys={**self.default_api_keys, **(api_keys or {})},
            default_model_overrides={**self.default_model_overrides, **(model_overrides or {})},
            progress_callback=progress_callback or self.progress_callback,
        )

    def create_for_tenant(
        self,
        _tenant_id: str,
        tenant_api_keys: dict[str, str] | None = None,
        tenant_model_overrides: dict[str, str] | None = None,
    ) -> PipelineExecutor:
        """Create an executor configured for a specific tenant.

        Merges tenant configuration with defaults.

        Args:
            tenant_id: Tenant ID
            tenant_api_keys: Tenant-specific API keys
            tenant_model_overrides: Tenant-specific model overrides

        Returns:
            Tenant-configured PipelineExecutor
        """
        return PipelineExecutor(
            registry=self.registry,
            default_api_keys={**self.default_api_keys, **(tenant_api_keys or {})},
            default_model_overrides={**self.default_model_overrides, **(tenant_model_overrides or {})},
            progress_callback=self.progress_callback,
        )
