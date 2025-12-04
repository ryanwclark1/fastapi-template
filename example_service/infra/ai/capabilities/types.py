"""Core types for AI capability discovery and provider routing.

This module defines the foundational types for the capability system:

- Capability: Enum of AI capabilities providers can offer
- CostUnit: How costs are measured (per token, per minute, etc.)
- QualityTier: Quality classification for cost/quality tradeoffs
- CapabilityMetadata: Detailed metadata about a provider's capability
- ProviderRegistration: Complete registration of a provider
- OperationResult: Standardized result from any AI operation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


class Capability(str, Enum):
    """AI capabilities that providers can offer.

    Each capability represents a specific AI function. Providers register
    which capabilities they support, enabling dynamic discovery and routing.

    Naming Convention:
        - Base capability: TRANSCRIPTION, LLM_GENERATION, etc.
        - Specialized variant: TRANSCRIPTION_DIARIZATION, LLM_STRUCTURED, etc.

    Usage:
        # Check if provider supports diarization
        if Capability.TRANSCRIPTION_DIARIZATION in provider.capabilities:
            result = await provider.transcribe(audio, speaker_diarization=True)
    """

    # Transcription capabilities
    TRANSCRIPTION = "transcription"
    TRANSCRIPTION_DIARIZATION = "transcription_diarization"
    TRANSCRIPTION_DUAL_CHANNEL = "transcription_dual_channel"
    TRANSCRIPTION_REALTIME = "transcription_realtime"

    # LLM capabilities
    LLM_GENERATION = "llm_generation"
    LLM_STRUCTURED = "llm_structured"
    LLM_STREAMING = "llm_streaming"
    LLM_VISION = "llm_vision"
    LLM_FUNCTION_CALLING = "llm_function_calling"

    # Specialized analysis (uses LLM internally but registered separately)
    SUMMARIZATION = "summarization"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    COACHING_ANALYSIS = "coaching_analysis"

    # PII capabilities
    PII_DETECTION = "pii_detection"
    PII_REDACTION = "pii_redaction"

    # Embedding capabilities (future)
    EMBEDDING = "embedding"
    EMBEDDING_MULTIMODAL = "embedding_multimodal"


class CostUnit(str, Enum):
    """Units for measuring provider costs.

    Different providers measure costs differently:
    - LLMs: per token (input and output may have different rates)
    - Transcription: per minute or per second of audio
    - PII: per request or per character
    """

    PER_1K_TOKENS = "per_1k_tokens"
    PER_1M_TOKENS = "per_1m_tokens"
    PER_MINUTE = "per_minute"
    PER_SECOND = "per_second"
    PER_CHARACTER = "per_character"
    PER_REQUEST = "per_request"
    FREE = "free"


class QualityTier(str, Enum):
    """Quality tier for provider capabilities.

    Used for:
    - Cost vs quality tradeoff decisions
    - Fallback chain ordering (prefer same tier or degrade gracefully)
    - Tenant-level quality constraints

    Tiers:
        ECONOMY: Cheapest option, may have limitations
        STANDARD: Good balance of cost and quality
        PREMIUM: Highest quality, typically more expensive
    """

    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


class ProviderType(str, Enum):
    """Type of provider for routing and billing purposes."""

    EXTERNAL = "external"  # Third-party API (OpenAI, Anthropic, etc.)
    INTERNAL = "internal"  # Self-hosted or internal service (Ollama, accent-*)
    HYBRID = "hybrid"  # Can switch between internal and external


@dataclass
class CapabilityMetadata:
    """Metadata about a provider's specific capability.

    Contains all information needed for:
    - Cost calculation and estimation
    - Quality-based routing decisions
    - Fallback chain construction
    - Feature compatibility checks

    Attributes:
        capability: The capability this metadata describes
        provider_name: Name of the provider offering this capability
        cost_per_unit: Cost in USD per unit (see cost_unit)
        cost_unit: How costs are measured (tokens, minutes, etc.)
        output_cost_per_unit: Separate cost for output (LLMs have input/output pricing)
        quality_tier: Quality classification for routing decisions
        priority: Fallback priority (lower = higher priority, tried first)
        supported_languages: ISO language codes supported (empty = all)
        supported_formats: File formats supported (for audio/image)
        max_input_size: Maximum input size (tokens for LLM, bytes for audio)
        supports_streaming: Whether streaming responses are supported
        supports_batch: Whether batch processing is supported
        avg_latency_ms: Average latency in milliseconds (for routing)
        rate_limit_rpm: Rate limit requests per minute (None = unlimited)
        model_name: Specific model name (gpt-4o, nova-2, etc.)
        version: Version of this capability metadata

    Example:
        deepgram_transcription = CapabilityMetadata(
            capability=Capability.TRANSCRIPTION_DIARIZATION,
            provider_name="deepgram",
            cost_per_unit=Decimal("0.0043"),
            cost_unit=CostUnit.PER_MINUTE,
            quality_tier=QualityTier.PREMIUM,
            priority=5,  # Preferred for diarization
            supported_languages=["en", "es", "fr", "de"],
            model_name="nova-2",
        )
    """

    capability: Capability
    provider_name: str

    # Cost information
    cost_per_unit: Decimal = Decimal("0")
    cost_unit: CostUnit = CostUnit.PER_REQUEST
    output_cost_per_unit: Decimal | None = None  # For LLMs with separate output pricing

    # Quality and routing
    quality_tier: QualityTier = QualityTier.STANDARD
    priority: int = 100  # Lower = higher priority for fallbacks

    # Feature support
    supported_languages: list[str] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)
    max_input_size: int | None = None
    supports_streaming: bool = False
    supports_batch: bool = False

    # Performance characteristics
    avg_latency_ms: int | None = None
    rate_limit_rpm: int | None = None

    # Model information
    model_name: str | None = None
    version: str = "1.0"

    def estimate_cost(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_seconds: float = 0,
        character_count: int = 0,
        request_count: int = 1,
    ) -> Decimal:
        """Estimate cost based on usage metrics.

        Args:
            input_tokens: Number of input tokens (LLM)
            output_tokens: Number of output tokens (LLM)
            duration_seconds: Audio duration in seconds (transcription)
            character_count: Number of characters (PII)
            request_count: Number of requests (per-request pricing)

        Returns:
            Estimated cost in USD
        """
        if self.cost_unit == CostUnit.FREE:
            return Decimal("0")

        if self.cost_unit == CostUnit.PER_1K_TOKENS:
            input_cost = (Decimal(input_tokens) / Decimal(1000)) * self.cost_per_unit
            output_cost = Decimal("0")
            if output_tokens and self.output_cost_per_unit:
                output_cost = (Decimal(output_tokens) / Decimal(1000)) * self.output_cost_per_unit
            return input_cost + output_cost

        if self.cost_unit == CostUnit.PER_1M_TOKENS:
            input_cost = (Decimal(input_tokens) / Decimal(1_000_000)) * self.cost_per_unit
            output_cost = Decimal("0")
            if output_tokens and self.output_cost_per_unit:
                output_cost = (
                    Decimal(output_tokens) / Decimal(1_000_000)
                ) * self.output_cost_per_unit
            return input_cost + output_cost

        if self.cost_unit == CostUnit.PER_MINUTE:
            return (Decimal(duration_seconds) / Decimal(60)) * self.cost_per_unit

        if self.cost_unit == CostUnit.PER_SECOND:
            return Decimal(duration_seconds) * self.cost_per_unit

        if self.cost_unit == CostUnit.PER_CHARACTER:
            return Decimal(character_count) * self.cost_per_unit

        if self.cost_unit == CostUnit.PER_REQUEST:
            return Decimal(request_count) * self.cost_per_unit

        return Decimal("0")


@dataclass
class ProviderRegistration:
    """Complete registration of a provider with all its capabilities.

    A provider can offer multiple capabilities. This registration contains
    the provider's identity and all capability metadata.

    Attributes:
        provider_name: Unique identifier for the provider (e.g., "openai", "deepgram")
        provider_type: Whether external API, internal service, or hybrid
        capabilities: List of capability metadata for each supported capability
        is_available: Whether the provider is currently available
        health_check_url: URL for health check endpoint (internal providers)
        requires_api_key: Whether this provider requires an API key
        documentation_url: URL to provider documentation

    Example:
        openai = ProviderRegistration(
            provider_name="openai",
            provider_type=ProviderType.EXTERNAL,
            capabilities=[
                CapabilityMetadata(Capability.LLM_GENERATION, "openai", ...),
                CapabilityMetadata(Capability.TRANSCRIPTION, "openai", ...),
            ],
            requires_api_key=True,
            documentation_url="https://platform.openai.com/docs",
        )
    """

    provider_name: str
    provider_type: ProviderType
    capabilities: list[CapabilityMetadata]
    is_available: bool = True
    health_check_url: str | None = None
    requires_api_key: bool = True
    documentation_url: str | None = None

    def get_capability(self, cap: Capability) -> CapabilityMetadata | None:
        """Get metadata for a specific capability.

        Args:
            cap: The capability to look up

        Returns:
            CapabilityMetadata if found, None otherwise
        """
        return next((c for c in self.capabilities if c.capability == cap), None)

    def supports(self, cap: Capability) -> bool:
        """Check if this provider supports a capability.

        Args:
            cap: The capability to check

        Returns:
            True if the provider supports this capability
        """
        return any(c.capability == cap for c in self.capabilities)

    def get_capabilities(self) -> list[Capability]:
        """Get list of all supported capabilities.

        Returns:
            List of Capability enums this provider supports
        """
        return [c.capability for c in self.capabilities]


@dataclass
class OperationResult:
    """Standardized result from any AI operation.

    All provider adapters return this format, enabling:
    - Consistent pipeline processing
    - Unified cost tracking
    - Standardized error handling

    Attributes:
        success: Whether the operation succeeded
        data: The operation output (TranscriptionResult, LLMResponse, etc.)
        provider_name: Which provider handled the request
        capability: Which capability was used
        usage: Raw usage metrics from provider (tokens, duration, etc.)
        cost_usd: Calculated cost in USD
        latency_ms: Operation latency in milliseconds
        error: Error message if failed
        retryable: Whether the error is retryable (for fallback logic)
        request_id: Provider's request ID for debugging
        timestamp: When the operation completed

    Example:
        result = OperationResult(
            success=True,
            data=TranscriptionResult(text="Hello world", ...),
            provider_name="deepgram",
            capability=Capability.TRANSCRIPTION,
            usage={"duration_seconds": 30.5},
            cost_usd=Decimal("0.0022"),
            latency_ms=1234.5,
        )
    """

    success: bool
    data: Any
    provider_name: str
    capability: Capability

    # Usage and cost
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: Decimal = Decimal("0")
    latency_ms: float = 0.0

    # Error handling
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False

    # Tracing
    request_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    job_id: UUID | None = None
    tenant_id: str | None = None

    @property
    def input_tokens(self) -> int:
        """Get input token count from usage."""
        value = self.usage.get("input_tokens", 0)
        return int(value) if value is not None else 0

    @property
    def output_tokens(self) -> int:
        """Get output token count from usage."""
        value = self.usage.get("output_tokens", 0)
        return int(value) if value is not None else 0

    @property
    def duration_seconds(self) -> float:
        """Get duration from usage (for transcription)."""
        value = self.usage.get("duration_seconds", 0.0)
        return float(value) if value is not None else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "provider_name": self.provider_name,
            "capability": self.capability.value,
            "usage": self.usage,
            "cost_usd": float(self.cost_usd),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "job_id": str(self.job_id) if self.job_id else None,
            "tenant_id": self.tenant_id,
        }
