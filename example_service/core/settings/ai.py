"""AI services settings for provider configuration and cost tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_ai_yaml_source

AIProvider = Literal[
    "openai",
    "anthropic",
    "google",
    "azure_openai",
    "deepgram",
    "assemblyai",
    "accent_stt",
    "ollama",
]

EmbeddingProvider = Literal["openai", "cohere", "local"]


# ===== Provider Settings Data Classes =====


@dataclass
class LLMSettings:
    """LLM provider settings container."""

    provider: str
    api_key: SecretStr | None
    model: str
    temperature: float
    max_tokens: int
    timeout: int
    max_retries: int
    base_url: str | None = None
    endpoint: str | None = None
    deployment_name: str | None = None
    api_version: str | None = None


@dataclass
class TranscriptionSettings:
    """Transcription provider settings container."""

    provider: str
    api_key: SecretStr | None
    model: str
    timeout: int
    max_retries: int
    service_url: str | None = None
    language: str | None = None
    speaker_labels: bool = True
    punctuation: bool = True


@dataclass
class EmbeddingSettings:
    """Embedding provider settings container."""

    provider: str
    api_key: SecretStr | None
    model: str
    timeout: int
    max_retries: int
    input_type: str | None = None
    device: str | None = None
    normalize: bool | None = None
    batch_size: int | None = None


class AISettings(BaseSettings):
    """AI services configuration settings.

    Environment variables use AI_ prefix.
    Example: AI_DEFAULT_LLM_PROVIDER=openai, AI_OPENAI_API_KEY=sk-...

    Supports multi-provider AI operations with tenant-level overrides:
    - LLM providers (OpenAI, Anthropic, Google, Azure OpenAI, Ollama)
    - Transcription providers (OpenAI Whisper, Deepgram, AssemblyAI, accent-stt)
    - Embedding providers (OpenAI, Cohere, local models)
    - PII redaction via accent-redaction service
    - Cost tracking and usage metrics
    """

    # ===== Default Provider Configuration =====
    default_llm_provider: AIProvider = Field(
        default="openai",
        description="Default LLM provider for text generation and analysis",
    )
    default_llm_model: str = Field(
        default="gpt-4o-mini",
        description="Default model for LLM operations (can be overridden per tenant)",
    )
    default_transcription_provider: AIProvider = Field(
        default="deepgram",
        description="Default provider for audio transcription",
    )
    default_transcription_model: str = Field(
        default="nova-2",
        description="Default transcription model (e.g., whisper-1, nova-2)",
    )
    default_embedding_provider: EmbeddingProvider = Field(
        default="openai",
        description="Default provider for text embeddings",
    )
    default_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Default embedding model (e.g., text-embedding-3-small, embed-english-v3.0)",
    )

    # ===== Provider API Keys (Service-level defaults) =====
    # These can be overridden at tenant level via database config
    openai_api_key: SecretStr | None = Field(
        default=None,
        description="OpenAI API key for GPT models and Whisper transcription",
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        description="Anthropic API key for Claude models",
    )
    google_api_key: SecretStr | None = Field(
        default=None,
        description="Google AI API key for Gemini models",
    )
    deepgram_api_key: SecretStr | None = Field(
        default=None,
        description="Deepgram API key for transcription",
    )
    assemblyai_api_key: SecretStr | None = Field(
        default=None,
        description="AssemblyAI API key for transcription with speaker diarization",
    )

    # Azure OpenAI specific
    azure_openai_api_key: SecretStr | None = Field(
        default=None,
        description="Azure OpenAI API key",
    )
    azure_openai_endpoint: str | None = Field(
        default=None,
        description="Azure OpenAI endpoint URL",
    )
    azure_openai_api_version: str = Field(
        default="2024-02-15-preview",
        description="Azure OpenAI API version",
    )
    azure_openai_deployment_name: str | None = Field(
        default=None,
        description="Azure OpenAI deployment name",
    )

    # Ollama (self-hosted)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL for local/self-hosted models",
    )
    ollama_default_model: str = Field(
        default="llama3.1",
        description="Default Ollama model name",
    )

    # ===== Internal AI Services =====
    accent_stt_url: str = Field(
        default="http://accent-stt:8000",
        description="URL for internal accent-stt transcription service",
    )
    accent_stt_api_key: SecretStr | None = Field(
        default=None,
        description="API key for accent-stt service (if required)",
    )
    accent_redaction_url: str = Field(
        default="http://accent-redaction:8000",
        description="URL for internal accent-redaction PII masking service",
    )
    accent_redaction_api_key: SecretStr | None = Field(
        default=None,
        description="API key for accent-redaction service (if required)",
    )

    # ===== Embedding Providers =====
    cohere_api_key: SecretStr | None = Field(
        default=None,
        description="Cohere API key for embeddings",
    )
    cohere_embedding_model: str = Field(
        default="embed-english-v3.0",
        description="Cohere embedding model",
    )
    cohere_input_type: Literal[
        "search_document", "search_query", "classification", "clustering"
    ] = Field(
        default="search_document",
        description="Cohere input type for embeddings",
    )

    # Local embedding configuration
    local_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model name for local embeddings",
    )
    local_embedding_device: Literal["cpu", "cuda"] = Field(
        default="cpu",
        description="Device to run local embedding model on",
    )
    local_embedding_normalize: bool = Field(
        default=True,
        description="Normalize embedding vectors to unit length",
    )
    local_embedding_batch_size: int = Field(
        default=32,
        ge=1,
        le=256,
        description="Batch size for local embedding generation",
    )

    # ===== Feature Toggles =====
    enable_transcription: bool = Field(
        default=True,
        description="Enable audio transcription features globally",
    )
    enable_pii_redaction: bool = Field(
        default=True,
        description="Enable PII redaction/masking features globally",
    )
    enable_summarization: bool = Field(
        default=True,
        description="Enable conversation summarization features globally",
    )
    enable_sentiment_analysis: bool = Field(
        default=True,
        description="Enable sentiment analysis features globally",
    )
    enable_coaching_analysis: bool = Field(
        default=True,
        description="Enable coaching/performance analysis features globally",
    )

    # ===== Cost Tracking & Metrics =====
    enable_cost_tracking: bool = Field(
        default=True,
        description="Track AI usage costs per tenant and operation",
    )
    cost_tracking_interval_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Interval for aggregating and storing cost metrics (60-3600s)",
    )
    enable_usage_metrics: bool = Field(
        default=True,
        description="Collect and store detailed usage metrics (tokens, duration, etc.)",
    )

    # Cost per 1M tokens (updated periodically, can be overridden in DB)
    openai_gpt4_input_cost_per_1m: float = Field(
        default=10.0,
        description="OpenAI GPT-4 input cost per 1M tokens (USD)",
    )
    openai_gpt4_output_cost_per_1m: float = Field(
        default=30.0,
        description="OpenAI GPT-4 output cost per 1M tokens (USD)",
    )
    openai_gpt4o_mini_input_cost_per_1m: float = Field(
        default=0.15,
        description="OpenAI GPT-4o-mini input cost per 1M tokens (USD)",
    )
    openai_gpt4o_mini_output_cost_per_1m: float = Field(
        default=0.60,
        description="OpenAI GPT-4o-mini output cost per 1M tokens (USD)",
    )
    anthropic_claude_input_cost_per_1m: float = Field(
        default=3.0,
        description="Anthropic Claude input cost per 1M tokens (USD)",
    )
    anthropic_claude_output_cost_per_1m: float = Field(
        default=15.0,
        description="Anthropic Claude output cost per 1M tokens (USD)",
    )

    # Transcription costs (per minute)
    deepgram_cost_per_minute: float = Field(
        default=0.0043,
        description="Deepgram Nova-2 cost per minute of audio (USD)",
    )
    assemblyai_cost_per_minute: float = Field(
        default=0.00037,
        description="AssemblyAI cost per minute of audio (USD)",
    )
    openai_whisper_cost_per_minute: float = Field(
        default=0.006,
        description="OpenAI Whisper cost per minute of audio (USD)",
    )

    # ===== Processing Configuration =====
    max_audio_duration_seconds: int = Field(
        default=7200,  # 2 hours
        ge=60,
        le=14400,  # 4 hours max
        description="Maximum audio duration for transcription (60s - 4 hours)",
    )
    max_concurrent_transcriptions: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent transcription jobs per tenant",
    )
    transcription_timeout_seconds: int = Field(
        default=600,  # 10 minutes
        ge=60,
        le=3600,
        description="Timeout for transcription operations (60s - 1 hour)",
    )

    # Dual-channel audio processing
    enable_dual_channel: bool = Field(
        default=True,
        description="Enable dual-channel audio processing for call recordings",
    )
    dual_channel_merge_strategy: Literal["timestamp", "sequential", "interleaved"] = (
        Field(
            default="timestamp",
            description="Strategy for merging dual-channel transcripts (timestamp|sequential|interleaved)",
        )
    )

    # ===== PII Redaction Configuration =====
    default_pii_entity_types: list[str] = Field(
        default_factory=lambda: [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "US_SSN",
            "US_PASSPORT",
            "MEDICAL_LICENSE",
            "IP_ADDRESS",
            "LOCATION",
        ],
        description="Default PII entity types to detect and redact",
    )
    pii_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for PII detection (0.0-1.0)",
    )
    pii_redaction_method: Literal["mask", "replace", "hash", "remove"] = Field(
        default="mask",
        description="Default PII redaction method (mask|replace|hash|remove)",
    )

    # ===== LLM Configuration =====
    llm_max_tokens: int = Field(
        default=4096,
        ge=256,
        le=32768,
        description="Maximum tokens for LLM responses",
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Default temperature for LLM generation (0.0-2.0)",
    )
    llm_request_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Timeout for LLM API requests (10s - 10min)",
    )

    # ===== Retry & Circuit Breaker =====
    enable_retry: bool = Field(
        default=True,
        description="Enable automatic retry for failed AI operations",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed operations",
    )
    retry_delay_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Initial delay between retries (exponential backoff)",
    )

    # ===== Caching =====
    enable_response_caching: bool = Field(
        default=False,
        description="Cache AI responses for identical inputs (requires Redis)",
    )
    cache_ttl_seconds: int = Field(
        default=3600,  # 1 hour
        ge=60,
        le=86400,  # 24 hours
        description="TTL for cached AI responses (60s - 24 hours)",
    )

    # ===== Budget Enforcement =====
    enable_budget_enforcement: bool = Field(
        default=True,
        description="Enable per-tenant budget tracking and enforcement",
    )
    default_daily_budget_usd: float | None = Field(
        default=None,
        description="Default daily budget per tenant (None = unlimited)",
    )
    default_monthly_budget_usd: float | None = Field(
        default=100.0,
        description="Default monthly budget per tenant (None = unlimited)",
    )
    budget_warn_threshold_percent: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Budget usage percentage at which to warn (0-100)",
    )
    budget_policy: Literal["warn", "soft_block", "hard_block"] = Field(
        default="warn",
        description="Budget enforcement policy: warn, soft_block, or hard_block",
    )

    # ===== Pipeline Configuration =====
    enable_pipeline_api: bool = Field(
        default=True,
        description="Enable the new pipeline-based AI API",
    )
    enable_pipeline_tracing: bool = Field(
        default=True,
        description="Enable OpenTelemetry tracing for pipelines",
    )
    enable_pipeline_metrics: bool = Field(
        default=True,
        description="Enable Prometheus metrics for pipelines",
    )

    # ===== Rate Limiting =====
    enable_rate_limiting: bool = Field(
        default=True,
        description="Enable per-tenant rate limiting for AI pipelines",
    )
    rate_limit_requests_per_minute: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Maximum pipeline execution requests per tenant per minute",
    )
    rate_limit_concurrent_executions: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent pipeline executions per tenant",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Rate limit window size in seconds",
    )

    @field_validator("default_llm_provider", "default_transcription_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name against supported providers."""
        valid_providers = {
            "openai",
            "anthropic",
            "google",
            "azure_openai",
            "deepgram",
            "assemblyai",
            "accent_stt",
            "ollama",
        }
        if v not in valid_providers:
            raise ValueError(
                f"Invalid provider: {v}. Must be one of: {', '.join(valid_providers)}"
            )
        return v

    @field_validator("default_embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, v: str) -> str:
        """Validate embedding provider name."""
        valid_providers = {"openai", "cohere", "local"}
        if v not in valid_providers:
            raise ValueError(
                f"Invalid embedding provider: {v}. Must be one of: {', '.join(valid_providers)}"
            )
        return v

    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,  # Immutable settings
        extra="ignore",
        env_ignore_empty=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_ai_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def has_llm_provider(self) -> bool:
        """Check if any LLM provider is configured."""
        return any([
            self.openai_api_key,
            self.anthropic_api_key,
            self.google_api_key,
            self.azure_openai_api_key,
            self.ollama_base_url,
        ])

    @property
    def has_transcription_provider(self) -> bool:
        """Check if any transcription provider is configured."""
        return any([
            self.openai_api_key,
            self.deepgram_api_key,
            self.assemblyai_api_key,
            self.accent_stt_url,
        ])

    @property
    def has_embedding_provider(self) -> bool:
        """Check if any embedding provider is configured."""
        return any([
            self.openai_api_key,  # OpenAI can be used for embeddings
            self.cohere_api_key,
            True,  # Local embeddings are always available
        ])

    @computed_field
    @property
    def available_llm_providers(self) -> list[str]:
        """Get list of available LLM providers (those with API keys configured)."""
        providers = []
        if self.openai_api_key:
            providers.append("openai")
        if self.anthropic_api_key:
            providers.append("anthropic")
        if self.google_api_key:
            providers.append("google")
        if (
            self.azure_openai_api_key
            and self.azure_openai_endpoint
            and self.azure_openai_deployment_name
        ):
            providers.append("azure_openai")
        if self.ollama_base_url:
            providers.append("ollama")
        return providers

    @computed_field
    @property
    def available_transcription_providers(self) -> list[str]:
        """Get list of available transcription providers."""
        providers = []
        if self.openai_api_key:
            providers.append("openai")
        if self.deepgram_api_key:
            providers.append("deepgram")
        if self.assemblyai_api_key:
            providers.append("assemblyai")
        if self.accent_stt_url:
            providers.append("accent_stt")
        return providers

    @computed_field
    @property
    def available_embedding_providers(self) -> list[str]:
        """Get list of available embedding providers."""
        providers = ["local"]  # Local embeddings always available
        if self.openai_api_key:
            providers.append("openai")
        if self.cohere_api_key:
            providers.append("cohere")
        return providers

    @computed_field
    @property
    def is_configured(self) -> bool:
        """Check if at least one provider is properly configured."""
        return bool(
            self.has_llm_provider
            or self.has_transcription_provider
            or self.has_embedding_provider
        )

    def get_provider_api_key(self, provider: str) -> SecretStr | None:
        """Get API key for specified provider."""
        provider_keys = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
            "azure_openai": self.azure_openai_api_key,
            "deepgram": self.deepgram_api_key,
            "assemblyai": self.assemblyai_api_key,
            "accent_stt": self.accent_stt_api_key,
            "accent_redaction": self.accent_redaction_api_key,
            "cohere": self.cohere_api_key,
        }
        return provider_keys.get(provider)

    # ===== Helper Methods for Provider Settings =====

    def get_llm_settings(
        self,
        provider: str | None = None,
    ) -> LLMSettings:
        """Get settings for specified LLM provider or default.

        Args:
            provider: Provider name or None for default.

        Returns:
            LLMSettings object with provider configuration.

        Raises:
            ValueError: If provider is invalid or not configured.
        """
        provider = provider or self.default_llm_provider

        if provider == "openai":
            if not self.openai_api_key:
                msg = "OpenAI API key not configured"
                raise ValueError(msg)
            return LLMSettings(
                provider="openai",
                api_key=self.openai_api_key,
                model=self.default_llm_model,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "anthropic":
            if not self.anthropic_api_key:
                msg = "Anthropic API key not configured"
                raise ValueError(msg)
            return LLMSettings(
                provider="anthropic",
                api_key=self.anthropic_api_key,
                model=self.default_llm_model,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "google":
            if not self.google_api_key:
                msg = "Google AI API key not configured"
                raise ValueError(msg)
            return LLMSettings(
                provider="google",
                api_key=self.google_api_key,
                model=self.default_llm_model,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "azure_openai":
            if (
                not self.azure_openai_api_key
                or not self.azure_openai_endpoint
                or not self.azure_openai_deployment_name
            ):
                msg = "Azure OpenAI not fully configured (requires api_key, endpoint, and deployment_name)"
                raise ValueError(msg)
            return LLMSettings(
                provider="azure_openai",
                api_key=self.azure_openai_api_key,
                model=self.azure_openai_deployment_name,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
                endpoint=self.azure_openai_endpoint,
                deployment_name=self.azure_openai_deployment_name,
                api_version=self.azure_openai_api_version,
            )
        if provider == "ollama":
            return LLMSettings(
                provider="ollama",
                api_key=None,
                model=self.ollama_default_model,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
                base_url=self.ollama_base_url,
            )
        raise ValueError(f"Invalid LLM provider: {provider}")

    def get_transcription_settings(
        self,
        provider: str | None = None,
    ) -> TranscriptionSettings:
        """Get settings for specified transcription provider or default.

        Args:
            provider: Provider name or None for default.

        Returns:
            TranscriptionSettings object with provider configuration.

        Raises:
            ValueError: If provider is invalid or not configured.
        """
        provider = provider or self.default_transcription_provider

        if provider == "openai":
            if not self.openai_api_key:
                msg = "OpenAI API key not configured for transcription"
                raise ValueError(msg)
            return TranscriptionSettings(
                provider="openai",
                api_key=self.openai_api_key,
                model=self.default_transcription_model,
                timeout=self.transcription_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "deepgram":
            if not self.deepgram_api_key:
                msg = "Deepgram API key not configured"
                raise ValueError(msg)
            return TranscriptionSettings(
                provider="deepgram",
                api_key=self.deepgram_api_key,
                model=self.default_transcription_model,
                timeout=self.transcription_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "assemblyai":
            if not self.assemblyai_api_key:
                msg = "AssemblyAI API key not configured"
                raise ValueError(msg)
            return TranscriptionSettings(
                provider="assemblyai",
                api_key=self.assemblyai_api_key,
                model=self.default_transcription_model,
                timeout=self.transcription_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "accent_stt":
            return TranscriptionSettings(
                provider="accent_stt",
                api_key=self.accent_stt_api_key,
                model="accent-stt",
                timeout=self.transcription_timeout_seconds,
                max_retries=self.max_retries,
                service_url=self.accent_stt_url,
            )
        raise ValueError(f"Invalid transcription provider: {provider}")

    def get_embedding_settings(
        self,
        provider: str | None = None,
    ) -> EmbeddingSettings:
        """Get settings for specified embedding provider or default.

        Args:
            provider: Provider name or None for default.

        Returns:
            EmbeddingSettings object with provider configuration.

        Raises:
            ValueError: If provider is invalid or not configured.
        """
        provider = provider or self.default_embedding_provider

        if provider == "openai":
            if not self.openai_api_key:
                msg = "OpenAI API key not configured for embeddings"
                raise ValueError(msg)
            return EmbeddingSettings(
                provider="openai",
                api_key=self.openai_api_key,
                model=self.default_embedding_model,
                timeout=self.llm_request_timeout_seconds,
                max_retries=self.max_retries,
            )
        if provider == "cohere":
            if not self.cohere_api_key:
                msg = "Cohere API key not configured"
                raise ValueError(msg)
            return EmbeddingSettings(
                provider="cohere",
                api_key=self.cohere_api_key,
                model=self.cohere_embedding_model,
                timeout=30,  # Cohere typically faster
                max_retries=self.max_retries,
                input_type=self.cohere_input_type,
            )
        if provider == "local":
            return EmbeddingSettings(
                provider="local",
                api_key=None,
                model=self.local_embedding_model,
                timeout=300,  # Local can take longer
                max_retries=1,  # No retries for local
                device=self.local_embedding_device,
                normalize=self.local_embedding_normalize,
                batch_size=self.local_embedding_batch_size,
            )
        raise ValueError(f"Invalid embedding provider: {provider}")
