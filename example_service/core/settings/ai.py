"""AI services settings for provider configuration and cost tracking."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
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


class AISettings(BaseSettings):
    """AI services configuration settings.

    Environment variables use AI_ prefix.
    Example: AI_DEFAULT_LLM_PROVIDER=openai, AI_OPENAI_API_KEY=sk-...

    Supports multi-provider AI operations with tenant-level overrides:
    - LLM providers (OpenAI, Anthropic, Google, Azure OpenAI, Ollama)
    - Transcription providers (OpenAI Whisper, Deepgram, AssemblyAI, accent-stt)
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
    dual_channel_merge_strategy: Literal["timestamp", "sequential", "interleaved"] = Field(
        default="timestamp",
        description="Strategy for merging dual-channel transcripts (timestamp|sequential|interleaved)",
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
        return any(
            [
                self.openai_api_key,
                self.anthropic_api_key,
                self.google_api_key,
                self.azure_openai_api_key,
                self.ollama_base_url,
            ]
        )

    @property
    def has_transcription_provider(self) -> bool:
        """Check if any transcription provider is configured."""
        return any(
            [
                self.openai_api_key,
                self.deepgram_api_key,
                self.assemblyai_api_key,
                self.accent_stt_url,
            ]
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
        }
        return provider_keys.get(provider)
