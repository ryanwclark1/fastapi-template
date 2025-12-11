"""GraphQL types for the AI feature.

Provides:
- AIJobType: GraphQL representation of an AI processing job
- AIUsageLogType: GraphQL representation of AI usage/cost metrics
- TenantAIConfigType: Tenant-specific AI configuration
- TenantAIFeatureType: Tenant AI feature flags
- Input types for creating/managing AI jobs
- Connection types for pagination
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated

import strawberry
from strawberry.scalars import JSON

from example_service.features.graphql.types.base import PageInfoType
from example_service.utils.runtime_dependencies import require_runtime_dependency

if TYPE_CHECKING:
    from example_service.features.ai.models import (
        AIJob,
        AIUsageLog,
        TenantAIConfig,
        TenantAIFeature,
    )

require_runtime_dependency(datetime, strawberry, JSON, PageInfoType)


# --- Enums ---


@strawberry.enum(description="Types of AI processing jobs")
class AIJobTypeEnum(Enum):
    """AI job type enum."""

    TRANSCRIPTION = "transcription"
    PII_REDACTION = "pii_redaction"
    SUMMARY = "summary"
    SENTIMENT = "sentiment"
    COACHING = "coaching"
    FULL_ANALYSIS = "full_analysis"


@strawberry.enum(description="Status of AI processing jobs")
class AIJobStatusEnum(Enum):
    """AI job status enum."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@strawberry.enum(description="AI provider category types")
class AIProviderTypeEnum(Enum):
    """AI provider type enum."""

    LLM = "llm"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"
    IMAGE = "image"
    PII_REDACTION = "pii_redaction"


# --- Output Types ---


@strawberry.type(description="AI processing job")
class AIJobType:
    """GraphQL type for AI Job entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    tenant_id: str = strawberry.field(description="Tenant identifier")
    job_type: AIJobTypeEnum = strawberry.field(description="Type of AI processing job")
    status: AIJobStatusEnum = strawberry.field(description="Current job status")
    input_data: JSON = strawberry.field(description="Job input parameters and data references")
    result_data: JSON | None = strawberry.field(description="Processing results")
    error_message: str | None = strawberry.field(description="Error details if failed")
    progress_percentage: int = strawberry.field(description="Progress indicator (0-100)")
    current_step: str | None = strawberry.field(description="Current processing step")
    started_at: datetime | None = strawberry.field(description="When processing started")
    completed_at: datetime | None = strawberry.field(description="When processing completed")
    duration_seconds: float | None = strawberry.field(description="Total processing duration")
    created_at: datetime = strawberry.field(description="When the job was created")
    updated_at: datetime = strawberry.field(description="When the job was last updated")
    created_by_id: strawberry.ID | None = strawberry.field(description="User who created the job")

    @classmethod
    def from_model(cls, job: AIJob) -> AIJobType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(job.id)),
            tenant_id=job.tenant_id,
            job_type=AIJobTypeEnum(job.job_type),
            status=AIJobStatusEnum(job.status),
            input_data=job.input_data,
            result_data=job.result_data,
            error_message=job.error_message,
            progress_percentage=job.progress_percentage,
            current_step=job.current_step,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=job.duration_seconds,
            created_at=job.created_at,
            updated_at=job.updated_at,
            created_by_id=strawberry.ID(str(job.created_by_id)) if job.created_by_id else None,
        )


@strawberry.type(description="AI usage and cost tracking record")
class AIUsageLogType:
    """GraphQL type for AI Usage Log entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    tenant_id: str = strawberry.field(description="Tenant identifier")
    job_id: strawberry.ID | None = strawberry.field(description="Associated AI job ID")
    provider_name: str = strawberry.field(description="AI provider (openai, anthropic, etc.)")
    model_name: str = strawberry.field(description="Specific model used")
    operation_type: str = strawberry.field(description="Type of operation performed")
    input_tokens: int | None = strawberry.field(description="Input tokens (LLM)")
    output_tokens: int | None = strawberry.field(description="Output tokens (LLM)")
    audio_seconds: float | None = strawberry.field(description="Audio duration (transcription)")
    characters_processed: int | None = strawberry.field(description="Characters processed")
    cost_usd: float = strawberry.field(description="Calculated cost in USD")
    cost_calculation_method: str | None = strawberry.field(description="How cost was calculated")
    duration_seconds: float = strawberry.field(description="Operation duration")
    success: bool = strawberry.field(description="Whether operation succeeded")
    error_message: str | None = strawberry.field(description="Error if failed")
    metadata: JSON | None = strawberry.field(description="Additional operation metadata")
    created_at: datetime = strawberry.field(description="When the log was created")

    @classmethod
    def from_model(cls, log: AIUsageLog) -> AIUsageLogType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(log.id)),
            tenant_id=log.tenant_id,
            job_id=strawberry.ID(str(log.job_id)) if log.job_id else None,
            provider_name=log.provider_name,
            model_name=log.model_name,
            operation_type=log.operation_type,
            input_tokens=log.input_tokens,
            output_tokens=log.output_tokens,
            audio_seconds=log.audio_seconds,
            characters_processed=log.characters_processed,
            cost_usd=log.cost_usd,
            cost_calculation_method=log.cost_calculation_method,
            duration_seconds=log.duration_seconds,
            success=log.success,
            error_message=log.error_message,
            metadata=log.metadata_json,
            created_at=log.created_at,
        )


@strawberry.type(description="Tenant-specific AI provider configuration")
class TenantAIConfigType:
    """GraphQL type for Tenant AI Config entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    tenant_id: str = strawberry.field(description="Tenant identifier")
    provider_type: AIProviderTypeEnum = strawberry.field(description="Provider category")
    provider_name: str = strawberry.field(description="Provider name (openai, anthropic, etc.)")
    model_name: str | None = strawberry.field(description="Optional model override")
    config: JSON | None = strawberry.field(description="Additional provider configuration")
    is_active: bool = strawberry.field(description="Whether this config is active")
    created_at: datetime = strawberry.field(description="When the config was created")
    updated_at: datetime = strawberry.field(description="When the config was last updated")

    @classmethod
    def from_model(cls, config: TenantAIConfig) -> TenantAIConfigType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(config.id)),
            tenant_id=config.tenant_id,
            provider_type=AIProviderTypeEnum(config.provider_type),
            provider_name=config.provider_name,
            model_name=config.model_name,
            config=config.config_json,
            is_active=config.is_active,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


@strawberry.type(description="Tenant AI feature flags and configuration")
class TenantAIFeatureType:
    """GraphQL type for Tenant AI Feature entity."""

    tenant_id: str = strawberry.field(description="Tenant identifier")
    transcription_enabled: bool = strawberry.field(description="Transcription feature enabled")
    pii_redaction_enabled: bool = strawberry.field(description="PII redaction feature enabled")
    summary_enabled: bool = strawberry.field(description="Summary feature enabled")
    sentiment_enabled: bool = strawberry.field(description="Sentiment analysis enabled")
    coaching_enabled: bool = strawberry.field(description="Coaching feature enabled")
    pii_entity_types: list[str] | None = strawberry.field(description="PII entity types to detect")
    pii_confidence_threshold: float | None = strawberry.field(description="PII confidence threshold")
    max_audio_duration_seconds: int | None = strawberry.field(description="Max audio duration")
    max_concurrent_jobs: int | None = strawberry.field(description="Max concurrent AI jobs")
    monthly_budget_usd: float | None = strawberry.field(description="Monthly spending limit")
    enable_cost_alerts: bool = strawberry.field(description="Cost alert notifications enabled")
    created_at: datetime = strawberry.field(description="When created")
    updated_at: datetime = strawberry.field(description="When last updated")

    @classmethod
    def from_model(cls, feature: TenantAIFeature) -> TenantAIFeatureType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            tenant_id=feature.tenant_id,
            transcription_enabled=feature.transcription_enabled,
            pii_redaction_enabled=feature.pii_redaction_enabled,
            summary_enabled=feature.summary_enabled,
            sentiment_enabled=feature.sentiment_enabled,
            coaching_enabled=feature.coaching_enabled,
            pii_entity_types=feature.pii_entity_types,
            pii_confidence_threshold=feature.pii_confidence_threshold,
            max_audio_duration_seconds=feature.max_audio_duration_seconds,
            max_concurrent_jobs=feature.max_concurrent_jobs,
            monthly_budget_usd=feature.monthly_budget_usd,
            enable_cost_alerts=feature.enable_cost_alerts,
            created_at=feature.created_at,
            updated_at=feature.updated_at,
        )


@strawberry.type(description="AI usage statistics summary")
class AIUsageStatsType:
    """Aggregated AI usage statistics."""

    total_jobs: int = strawberry.field(description="Total number of AI jobs")
    completed_jobs: int = strawberry.field(description="Successfully completed jobs")
    failed_jobs: int = strawberry.field(description="Failed jobs")
    pending_jobs: int = strawberry.field(description="Pending/processing jobs")
    total_cost_usd: float = strawberry.field(description="Total cost in USD")
    total_tokens: int = strawberry.field(description="Total tokens consumed")
    total_audio_seconds: float = strawberry.field(description="Total audio processed (seconds)")
    avg_job_duration_seconds: float | None = strawberry.field(description="Average job duration")
    cost_by_provider: JSON = strawberry.field(description="Cost breakdown by provider")
    cost_by_operation: JSON = strawberry.field(description="Cost breakdown by operation type")


@strawberry.type(description="AI cost estimation result")
class AICostEstimateType:
    """Estimated cost for an AI operation."""

    job_type: AIJobTypeEnum = strawberry.field(description="Type of job")
    estimated_cost_usd: float = strawberry.field(description="Estimated cost in USD")
    estimated_tokens: int | None = strawberry.field(description="Estimated token usage")
    estimated_duration_seconds: float | None = strawberry.field(description="Estimated duration")
    provider: str = strawberry.field(description="Provider that would be used")
    model: str = strawberry.field(description="Model that would be used")
    confidence: float = strawberry.field(description="Confidence in estimate (0-1)")


# --- Input Types ---


@strawberry.input(description="Input for creating a new AI job")
class CreateAIJobInput:
    """Input for createAIJob mutation."""

    job_type: AIJobTypeEnum = strawberry.field(description="Type of AI job to create")
    input_data: JSON = strawberry.field(description="Job input parameters")


@strawberry.input(description="Input for estimating AI job cost")
class EstimateAICostInput:
    """Input for estimateAICost query."""

    job_type: AIJobTypeEnum = strawberry.field(description="Type of AI job")
    input_data: JSON = strawberry.field(description="Job input parameters for estimation")


@strawberry.input(description="Filter for AI jobs query")
class AIJobFilterInput:
    """Filter input for AI jobs query."""

    status: AIJobStatusEnum | None = strawberry.field(
        default=None, description="Filter by status",
    )
    job_type: AIJobTypeEnum | None = strawberry.field(
        default=None, description="Filter by job type",
    )
    created_after: datetime | None = strawberry.field(
        default=None, description="Jobs created after this time",
    )
    created_before: datetime | None = strawberry.field(
        default=None, description="Jobs created before this time",
    )


@strawberry.input(description="Filter for AI usage logs query")
class AIUsageFilterInput:
    """Filter input for AI usage logs query."""

    provider_name: str | None = strawberry.field(
        default=None, description="Filter by provider",
    )
    operation_type: str | None = strawberry.field(
        default=None, description="Filter by operation type",
    )
    success: bool | None = strawberry.field(
        default=None, description="Filter by success status",
    )
    created_after: datetime | None = strawberry.field(
        default=None, description="Logs created after this time",
    )
    created_before: datetime | None = strawberry.field(
        default=None, description="Logs created before this time",
    )


# --- Payload Types ---


@strawberry.type(description="Successful AI job operation result")
class AIJobSuccess:
    """Success payload for AI job mutations."""

    job: AIJobType = strawberry.field(description="The created/updated AI job")


@strawberry.type(description="Error result from an AI operation")
class AIJobError:
    """Error payload for AI job mutations."""

    code: str = strawberry.field(description="Error code")
    message: str = strawberry.field(description="Human-readable error message")
    field: str | None = strawberry.field(
        default=None, description="Field that caused the error",
    )


AIJobPayload = Annotated[
    AIJobSuccess | AIJobError,
    strawberry.union(name="AIJobPayload", description="Result of an AI job mutation"),
]


# --- Connection Types ---


@strawberry.type(description="Edge containing an AI job and its cursor")
class AIJobEdge:
    """Edge wrapper for paginated AI jobs."""

    node: AIJobType = strawberry.field(description="The AI job")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of AI jobs")
class AIJobConnection:
    """GraphQL Connection for cursor-paginated AI jobs."""

    edges: list[AIJobEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


@strawberry.type(description="Edge containing an AI usage log and its cursor")
class AIUsageLogEdge:
    """Edge wrapper for paginated AI usage logs."""

    node: AIUsageLogType = strawberry.field(description="The usage log")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of AI usage logs")
class AIUsageLogConnection:
    """GraphQL Connection for cursor-paginated AI usage logs."""

    edges: list[AIUsageLogEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


__all__ = [
    "AICostEstimateType",
    "AIJobConnection",
    "AIJobEdge",
    "AIJobError",
    "AIJobFilterInput",
    "AIJobPayload",
    "AIJobStatusEnum",
    "AIJobSuccess",
    "AIJobType",
    "AIJobTypeEnum",
    "AIProviderTypeEnum",
    "AIUsageFilterInput",
    "AIUsageLogConnection",
    "AIUsageLogEdge",
    "AIUsageLogType",
    "AIUsageStatsType",
    "CreateAIJobInput",
    "EstimateAICostInput",
    "TenantAIConfigType",
    "TenantAIFeatureType",
]
