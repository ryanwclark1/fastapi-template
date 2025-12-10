"""Database models for AI services.

Models:
- TenantAIConfig: Per-tenant AI provider configuration and API keys
- AIJob: Job tracking for async AI processing tasks
- AIUsageLog: Cost and usage metrics for AI operations
- TenantAIFeature: Feature flags for AI capabilities per tenant
"""

from __future__ import annotations

from datetime import UTC, datetime
import enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database.base import Base
from example_service.core.database.enums import (
    AIJobStatus as AIJobStatusEnum,
)
from example_service.core.database.enums import (
    AIJobType as AIJobTypeEnum,
)
from example_service.core.database.enums import (
    AIProviderType as AIProviderTypeEnum,
)
from example_service.core.models.tenant import Tenant
from example_service.core.models.user import User


class AIProviderType(str, enum.Enum):
    """AI provider category types."""

    LLM = "llm"  # Language models (GPT, Claude, etc.)
    TRANSCRIPTION = "transcription"  # Speech-to-text
    EMBEDDING = "embedding"  # Vector embeddings
    IMAGE = "image"  # Image generation/analysis
    PII_REDACTION = "pii_redaction"  # PII detection/masking


class AIJobType(str, enum.Enum):
    """Types of AI processing jobs."""

    TRANSCRIPTION = "transcription"
    PII_REDACTION = "pii_redaction"
    SUMMARY = "summary"
    SENTIMENT = "sentiment"
    COACHING = "coaching"
    FULL_ANALYSIS = "full_analysis"  # All of the above


class AIJobStatus(str, enum.Enum):
    """Status of AI processing jobs."""

    PENDING = "pending"  # Queued, not started
    PROCESSING = "processing"  # Currently being processed
    COMPLETED = "completed"  # Successfully completed
    FAILED = "failed"  # Failed with error
    CANCELLED = "cancelled"  # Cancelled by user/system


class TenantAIConfig(Base):
    """Tenant-specific AI provider configuration.

    Allows tenants to override default providers, models, and API keys.
    API keys are encrypted at rest using application-level encryption.

    Examples:
        # Tenant uses their own OpenAI key
        TenantAIConfig(
            tenant_id="tenant-123",
            provider_type=AIProviderType.LLM,
            provider_name="openai",
            model_name="gpt-4-turbo",
            encrypted_api_key=encrypt("sk-..."),
            is_active=True
        )

        # Tenant uses Deepgram for transcription
        TenantAIConfig(
            tenant_id="tenant-123",
            provider_type=AIProviderType.TRANSCRIPTION,
            provider_name="deepgram",
            encrypted_api_key=encrypt("..."),
            config_json={"language": "en", "model": "nova-2"}
        )
    """

    __tablename__ = "tenant_ai_configs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(AIProviderTypeEnum, nullable=False)
    provider_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="openai|anthropic|deepgram|etc"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(255), comment="Optional model override (e.g., gpt-4, claude-3)"
    )
    encrypted_api_key: Mapped[str | None] = mapped_column(
        Text, comment="Encrypted API key for provider"
    )
    config_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="Additional provider-specific configuration"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="ai_configs")
    created_by: Mapped[User | None] = relationship("User")

    __table_args__ = (
        Index(
            "ix_tenant_ai_configs_tenant_provider",
            "tenant_id",
            "provider_type",
            "provider_name",
        ),
        Index("ix_tenant_ai_configs_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<TenantAIConfig(tenant_id={self.tenant_id}, "
            f"provider={self.provider_name}, type={self.provider_type})>"
        )


class AIJob(Base):
    """AI processing job tracking.

    Tracks async AI processing jobs from submission through completion.
    Supports progress tracking, error handling, and result storage.

    Examples:
        # Transcription job
        AIJob(
            tenant_id="tenant-123",
            job_type=AIJobType.TRANSCRIPTION,
            status=AIJobStatus.PENDING,
            input_data={
                "audio_url": "s3://bucket/call.wav",
                "language": "en",
                "speaker_diarization": True
            },
            created_by_id=user_id
        )

        # Full analysis workflow
        AIJob(
            tenant_id="tenant-123",
            job_type=AIJobType.FULL_ANALYSIS,
            status=AIJobStatus.PROCESSING,
            input_data={
                "audio_urls": ["s3://bucket/agent.wav", "s3://bucket/customer.wav"],
                "enable_pii_redaction": True,
                "enable_summary": True,
                "enable_coaching": True
            },
            progress_percentage=45
        )
    """

    __tablename__ = "ai_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(AIJobTypeEnum, nullable=False)
    status: Mapped[str] = mapped_column(
        AIJobStatusEnum, default="PENDING", nullable=False
    )

    # Job configuration and data
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="Job input parameters and data references"
    )
    result_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="Processing results (transcripts, summaries, etc.)"
    )
    error_message: Mapped[str | None] = mapped_column(Text, comment="Error details if failed")

    # Progress tracking
    progress_percentage: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="0-100 progress indicator"
    )
    current_step: Mapped[str | None] = mapped_column(
        String(255), comment="Current processing step description"
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(comment="When processing started")
    completed_at: Mapped[datetime | None] = mapped_column(comment="When processing completed")
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, comment="Total processing duration"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant")
    created_by: Mapped[User | None] = relationship("User")
    usage_logs: Mapped[list[AIUsageLog]] = relationship(
        "AIUsageLog", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_ai_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_ai_jobs_tenant_type", "tenant_id", "job_type"),
        Index("ix_ai_jobs_created_at", "created_at"),
        Index("ix_ai_jobs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIJob(id={self.id}, tenant_id={self.tenant_id}, "
            f"type={self.job_type}, status={self.status})>"
        )


class AIUsageLog(Base):
    """AI usage and cost tracking.

    Records detailed metrics for each AI operation:
    - Provider and model used
    - Tokens consumed (input/output)
    - Calculated costs
    - Processing duration
    - Operation type

    Used for:
    - Per-tenant cost tracking and billing
    - Usage analytics and reporting
    - Cost optimization insights
    - Provider performance comparison

    Examples:
        AIUsageLog(
            tenant_id="tenant-123",
            job_id=job.id,
            provider_name="openai",
            model_name="gpt-4o-mini",
            operation_type="summarization",
            input_tokens=2000,
            output_tokens=500,
            cost_usd=0.003,
            duration_seconds=3.5
        )
    """

    __tablename__ = "ai_usage_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="SET NULL"), comment="Associated AI job"
    )

    # Provider information
    provider_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="openai|anthropic|deepgram|etc"
    )
    model_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Specific model used (gpt-4, nova-2, etc)"
    )
    operation_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="transcription|llm_generation|embedding|pii_detection",
    )

    # Usage metrics
    input_tokens: Mapped[int | None] = mapped_column(Integer, comment="Input tokens (LLM)")
    output_tokens: Mapped[int | None] = mapped_column(Integer, comment="Output tokens (LLM)")
    audio_seconds: Mapped[float | None] = mapped_column(
        Float, comment="Audio duration (transcription)"
    )
    characters_processed: Mapped[int | None] = mapped_column(
        Integer, comment="Characters processed (PII, etc.)"
    )

    # Cost tracking
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, comment="Calculated cost in USD")
    cost_calculation_method: Mapped[str | None] = mapped_column(
        String(50), comment="How cost was calculated (api_reported|estimated)"
    )

    # Performance metrics
    duration_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Operation duration"
    )
    success: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Whether operation succeeded"
    )
    error_message: Mapped[str | None] = mapped_column(Text, comment="Error if failed")

    # Additional metadata
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="Additional operation-specific metadata"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant")
    job: Mapped[AIJob | None] = relationship("AIJob", back_populates="usage_logs")

    __table_args__ = (
        Index("ix_ai_usage_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_usage_logs_tenant_provider", "tenant_id", "provider_name"),
        Index("ix_ai_usage_logs_job", "job_id"),
        Index("ix_ai_usage_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIUsageLog(tenant_id={self.tenant_id}, provider={self.provider_name}, "
            f"model={self.model_name}, cost=${self.cost_usd:.4f})>"
        )


class TenantAIFeature(Base):
    """Tenant-level AI feature flags and configuration.

    Controls which AI features are enabled for each tenant and provides
    feature-specific configuration (e.g., which PII entity types to detect).

    Examples:
        TenantAIFeature(
            tenant_id="tenant-123",
            transcription_enabled=True,
            pii_redaction_enabled=True,
            summary_enabled=True,
            sentiment_enabled=False,
            coaching_enabled=True,
            pii_entity_types=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"],
            max_audio_duration_seconds=3600
        )
    """

    __tablename__ = "tenant_ai_features"

    tenant_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Feature toggles
    transcription_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pii_redaction_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sentiment_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    coaching_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Feature-specific configuration
    pii_entity_types: Mapped[list[str] | None] = mapped_column(
        JSON, comment="List of PII entity types to detect/redact"
    )
    pii_confidence_threshold: Mapped[float | None] = mapped_column(
        Float, comment="Minimum confidence for PII detection (0.0-1.0)"
    )
    max_audio_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, comment="Maximum audio duration for transcription (override global)"
    )
    max_concurrent_jobs: Mapped[int | None] = mapped_column(
        Integer, comment="Maximum concurrent AI jobs (override global)"
    )

    # Cost controls
    monthly_budget_usd: Mapped[float | None] = mapped_column(
        Float, comment="Monthly AI spending limit in USD"
    )
    enable_cost_alerts: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Send alerts on high costs"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="ai_features")

    def __repr__(self) -> str:
        return f"<TenantAIFeature(tenant_id={self.tenant_id})>"
