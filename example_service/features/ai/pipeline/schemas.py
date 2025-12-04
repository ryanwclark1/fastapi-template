"""Pydantic schemas for the new pipeline-based AI API.

These schemas support the new capability-based, composable pipeline architecture
while maintaining compatibility with existing patterns.

Key Differences from Legacy Schemas:
- Pipeline-based execution (not workflow_type enum)
- Real-time event streaming support
- Granular progress tracking (25+ events vs 5 fixed points)
- Actual cost tracking (not hardcoded estimates)
- Budget enforcement integration
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class PipelineStatus(str, Enum):
    """Pipeline execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Individual step status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventCategory(str, Enum):
    """Event categories for filtering."""

    WORKFLOW = "workflow"
    STEP = "step"
    PROGRESS = "progress"
    COST = "cost"
    COMPENSATION = "compensation"


# =============================================================================
# Pipeline Execution Requests
# =============================================================================


class PipelineExecutionRequest(BaseModel):
    """Request to execute a predefined or custom pipeline.

    Example:
        {
            "pipeline_name": "call_analysis",
            "input_data": {
                "audio_url": "https://storage.example.com/call-123.mp3"
            },
            "options": {
                "include_coaching": true,
                "llm_provider_preference": ["anthropic", "openai"]
            }
        }
    """

    pipeline_name: str = Field(
        description="Name of predefined pipeline (call_analysis, transcription, etc.)"
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the pipeline (audio, text, etc.)",
        alias="input",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Pipeline-specific options (provider preferences, flags)",
    )
    async_processing: bool = Field(
        default=True,
        description="If true, returns immediately with execution_id for polling",
        alias="async_mode",
    )
    budget_limit_usd: Decimal | None = Field(
        default=None,
        description="Override budget limit for this execution",
    )

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "examples": [
                {
                    "pipeline_name": "call_analysis",
                    "input_data": {"audio_url": "https://storage.example.com/call.mp3"},
                    "options": {"include_coaching": True},
                    "async_processing": True,
                },
                {
                    "pipeline_name": "transcription",
                    "input_data": {"audio_url": "https://storage.example.com/call.mp3"},
                    "options": {"with_diarization": True},
                    "async_processing": False,
                },
            ],
        },
    }


class AudioUploadRequest(BaseModel):
    """Request for audio file upload execution.

    Used with multipart form data where audio is uploaded directly.
    """

    pipeline_name: str = Field(
        default="call_analysis",
        description="Pipeline to execute",
    )
    language: str = Field(
        default="en",
        description="Language code for transcription",
    )
    include_summary: bool = Field(
        default=True,
        description="Include summarization step",
    )
    include_sentiment: bool = Field(
        default=True,
        description="Include sentiment analysis",
    )
    include_coaching: bool = Field(
        default=True,
        description="Include coaching insights",
    )
    enable_pii_redaction: bool = Field(
        default=True,
        description="Redact PII from transcript",
    )


# =============================================================================
# Pipeline Execution Responses
# =============================================================================


class PipelineExecutionResponse(BaseModel):
    """Response from pipeline execution request."""

    execution_id: str = Field(description="Unique execution identifier")
    pipeline_name: str = Field(description="Name of pipeline being executed")
    pipeline_version: str = Field(description="Version of pipeline")
    status: PipelineStatus = Field(description="Current execution status")
    created_at: datetime = Field(description="When execution was created")
    estimated_duration_seconds: int | None = Field(
        default=None,
        description="Estimated duration based on pipeline definition",
    )
    estimated_cost_usd: str | None = Field(
        default=None,
        description="Estimated cost based on pipeline definition",
    )
    stream_url: str | None = Field(
        default=None,
        description="WebSocket URL for real-time events",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "execution_id": "exec-123e4567-e89b-12d3-a456-426614174000",
                "pipeline_name": "call_analysis",
                "pipeline_version": "1.0.0",
                "status": "running",
                "created_at": "2025-01-15T10:30:00Z",
                "estimated_duration_seconds": 120,
                "estimated_cost_usd": "0.15",
                "stream_url": "/ws/ai/executions/exec-123.../events",
            }
        }
    }


class StepResultSchema(BaseModel):
    """Result from a single pipeline step."""

    step_name: str = Field(description="Name of the step")
    status: StepStatus = Field(description="Step execution status")
    provider_used: str | None = Field(
        default=None,
        description="Provider that executed the step",
    )
    fallbacks_attempted: list[str] = Field(
        default_factory=list,
        description="Providers that failed before success",
    )
    retries: int = Field(default=0, description="Number of retry attempts")
    duration_ms: float | None = Field(
        default=None,
        description="Step duration in milliseconds",
    )
    cost_usd: str = Field(default="0", description="Step cost in USD")
    error: str | None = Field(default=None, description="Error message if failed")
    skipped_reason: str | None = Field(
        default=None,
        description="Reason if step was skipped",
    )


class PipelineResultResponse(BaseModel):
    """Complete pipeline execution result."""

    execution_id: str = Field(description="Execution identifier")
    pipeline_name: str = Field(description="Pipeline that was executed")
    pipeline_version: str = Field(description="Pipeline version")
    status: PipelineStatus = Field(description="Final execution status")
    success: bool = Field(description="Whether execution succeeded")

    # Output data
    output: dict[str, Any] = Field(
        default_factory=dict,
        description="Output data from all steps (transcript, summary, etc.)",
    )

    # Step details
    completed_steps: list[str] = Field(
        default_factory=list,
        description="List of completed step names",
    )
    failed_step: str | None = Field(
        default=None,
        description="Name of step that failed (if any)",
    )
    step_results: dict[str, StepResultSchema] = Field(
        default_factory=dict,
        description="Detailed results for each step",
    )

    # Metrics
    total_duration_ms: float = Field(description="Total execution duration")
    total_cost_usd: str = Field(description="Total cost in USD")

    # Timing
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Compensation
    compensation_performed: bool = Field(
        default=False,
        description="Whether saga compensation was executed",
    )
    compensated_steps: list[str] = Field(
        default_factory=list,
        description="Steps that were compensated",
    )

    # Error
    error: str | None = Field(default=None, description="Error message if failed")

    model_config = {
        "json_schema_extra": {
            "example": {
                "execution_id": "exec-123",
                "pipeline_name": "call_analysis",
                "pipeline_version": "1.0.0",
                "status": "completed",
                "success": True,
                "output": {
                    "transcript": {"text": "Hello, how can I help you today?", "segments": []},
                    "summary": {"text": "Customer called about billing inquiry..."},
                    "sentiment": {"overall": "positive", "score": 0.75},
                },
                "completed_steps": ["transcribe", "redact_pii", "summarize", "sentiment"],
                "step_results": {},
                "total_duration_ms": 45230.5,
                "total_cost_usd": "0.0847",
                "started_at": "2025-01-15T10:30:00Z",
                "completed_at": "2025-01-15T10:30:45Z",
            }
        }
    }


# =============================================================================
# Progress & Events
# =============================================================================


class ProgressResponse(BaseModel):
    """Current progress of pipeline execution."""

    execution_id: str = Field(description="Execution identifier")
    status: PipelineStatus = Field(description="Current status")
    progress_percent: float = Field(
        description="Progress percentage (0-100)",
        ge=0,
        le=100,
    )
    message: str = Field(description="Current progress message")
    current_step: str | None = Field(
        default=None,
        description="Currently executing step",
    )
    steps_completed: int = Field(description="Number of completed steps")
    total_steps: int = Field(description="Total number of steps")
    estimated_remaining_seconds: int | None = Field(
        default=None,
        description="Estimated time remaining",
    )
    current_cost_usd: str = Field(
        default="0",
        description="Cost incurred so far",
    )


class EventSchema(BaseModel):
    """Schema for real-time events."""

    event_id: str = Field(description="Unique event identifier")
    event_type: str = Field(description="Type of event")
    execution_id: str = Field(description="Parent execution identifier")
    timestamp: datetime = Field(description="When event occurred")
    category: EventCategory = Field(description="Event category")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data",
    )


class EventStreamRequest(BaseModel):
    """Request parameters for event streaming."""

    categories: list[EventCategory] | None = Field(
        default=None,
        description="Filter by event categories",
    )
    include_history: bool = Field(
        default=False,
        description="Include past events (not just live)",
    )


# =============================================================================
# Pipeline Discovery
# =============================================================================


class PipelineInfoSchema(BaseModel):
    """Information about an available pipeline."""

    name: str = Field(description="Pipeline name")
    version: str = Field(description="Pipeline version")
    description: str = Field(description="Human-readable description")
    tags: list[str] = Field(default_factory=list, description="Pipeline tags")
    step_count: int = Field(description="Number of steps")
    estimated_duration_seconds: int | None = Field(
        default=None,
        description="Estimated execution time",
    )
    estimated_cost_usd: str | None = Field(
        default=None,
        description="Estimated cost",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Capabilities this pipeline requires",
    )


class PipelineListResponse(BaseModel):
    """List of available pipelines."""

    pipelines: list[PipelineInfoSchema] = Field(description="Available pipelines")
    total: int = Field(description="Total count")


class CapabilityInfoSchema(BaseModel):
    """Information about an available capability."""

    capability: str = Field(description="Capability name")
    providers: list[str] = Field(description="Providers offering this capability")
    default_provider: str | None = Field(
        default=None,
        description="Default provider (highest priority)",
    )


class CapabilityListResponse(BaseModel):
    """List of available capabilities."""

    capabilities: list[CapabilityInfoSchema] = Field(
        description="Available capabilities",
    )


# =============================================================================
# Budget & Cost
# =============================================================================


class BudgetStatusResponse(BaseModel):
    """Current budget status for a tenant."""

    tenant_id: str = Field(description="Tenant identifier")
    period: str = Field(description="Budget period (daily, monthly)")
    current_spend_usd: str = Field(description="Amount spent in period")
    limit_usd: str | None = Field(
        default=None,
        description="Budget limit for period",
    )
    remaining_usd: str | None = Field(
        default=None,
        description="Remaining budget",
    )
    percent_used: float | None = Field(
        default=None,
        description="Percentage of budget used",
    )
    is_exceeded: bool = Field(
        default=False,
        description="Whether budget is exceeded",
    )
    policy: str = Field(
        default="warn",
        description="Enforcement policy (warn, soft_block, hard_block)",
    )


class SpendSummaryResponse(BaseModel):
    """Spend summary for a tenant."""

    tenant_id: str = Field(description="Tenant identifier")
    period: str = Field(description="Time period")
    start_date: datetime = Field(description="Period start")
    end_date: datetime = Field(description="Period end")
    total_spend_usd: str = Field(description="Total spend")
    record_count: int = Field(description="Number of operations")
    by_pipeline: dict[str, str] = Field(
        default_factory=dict,
        description="Spend by pipeline",
    )
    by_provider: dict[str, str] = Field(
        default_factory=dict,
        description="Spend by provider",
    )
    by_capability: dict[str, str] = Field(
        default_factory=dict,
        description="Spend by capability",
    )


class SetBudgetRequest(BaseModel):
    """Request to set budget limits."""

    daily_limit_usd: Decimal | None = Field(
        default=None,
        description="Daily spending limit",
    )
    monthly_limit_usd: Decimal | None = Field(
        default=None,
        description="Monthly spending limit",
    )
    warn_threshold_percent: float = Field(
        default=80.0,
        description="Percentage at which to warn",
        ge=0,
        le=100,
    )
    policy: str = Field(
        default="warn",
        description="Enforcement policy (warn, soft_block, hard_block)",
    )


# =============================================================================
# Provider Information
# =============================================================================


class ProviderInfoSchema(BaseModel):
    """Information about a registered provider."""

    name: str = Field(description="Provider name")
    provider_type: str = Field(description="internal or external")
    is_available: bool = Field(description="Whether provider is currently available")
    capabilities: list[str] = Field(description="Capabilities offered")
    requires_api_key: bool = Field(description="Whether API key is required")
    documentation_url: str | None = Field(
        default=None,
        description="Link to provider documentation",
    )


class ProviderListResponse(BaseModel):
    """List of registered providers."""

    providers: list[ProviderInfoSchema] = Field(description="Registered providers")
    total: int = Field(description="Total count")


# =============================================================================
# Error Responses
# =============================================================================


class BudgetExceededError(BaseModel):
    """Error response when budget is exceeded."""

    error: str = Field(default="budget_exceeded")
    message: str = Field(description="Human-readable message")
    current_spend_usd: str = Field(description="Current spend")
    limit_usd: str = Field(description="Budget limit")
    period: str = Field(description="Budget period")


class PipelineNotFoundError(BaseModel):
    """Error response when pipeline is not found."""

    error: str = Field(default="pipeline_not_found")
    message: str = Field(description="Human-readable message")
    requested_pipeline: str = Field(description="Pipeline that was requested")
    available_pipelines: list[str] = Field(description="Available pipeline names")


class ExecutionNotFoundError(BaseModel):
    """Error response when execution is not found."""

    error: str = Field(default="execution_not_found")
    message: str = Field(description="Human-readable message")
    execution_id: str = Field(description="Execution ID that was not found")


# Rebuild models that use forward references
SpendSummaryResponse.model_rebuild()
