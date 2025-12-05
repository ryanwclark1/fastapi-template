"""Base provider interfaces for AI services.

Defines protocol classes for different AI capabilities:
- TranscriptionProvider: Audio transcription (speech-to-text)
- LLMProvider: Large language model operations
- PIIRedactionProvider: PII detection and masking
- EmbeddingProvider: Vector embeddings

Each provider implements these protocols to ensure consistent API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

# =============================================================================
# Result Models (Pydantic for validation and serialization)
# =============================================================================


class TranscriptionSegment(BaseModel):
    """Single segment of transcribed audio with timing."""

    text: str
    start: float  # seconds
    end: float  # seconds
    speaker: str | None = None
    confidence: float | None = None
    words: list[dict[str, Any]] | None = None


class TranscriptionResult(BaseModel):
    """Complete transcription result."""

    text: str  # Full transcript
    segments: list[TranscriptionSegment]
    language: str | None = None
    duration_seconds: float | None = None
    speakers: dict[str, Any] | None = None  # Speaker diarization info
    provider_metadata: dict[str, Any] | None = None


class LLMMessage(BaseModel):
    """Message in LLM conversation."""

    role: str  # system, user, assistant
    content: str


class LLMResponse(BaseModel):
    """Response from LLM provider."""

    content: str
    model: str
    usage: dict[str, int] | None = None  # {input_tokens, output_tokens, total_tokens}
    finish_reason: str | None = None
    provider_metadata: dict[str, Any] | None = None


class PIIEntity(BaseModel):
    """Detected PII entity."""

    type: str  # PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.
    text: str  # Original text
    start: int  # Character position
    end: int  # Character position
    score: float  # Confidence score
    anonymized_text: str | None = None  # Replacement text


class PIIRedactionResult(BaseModel):
    """Result of PII redaction operation."""

    original_text: str
    redacted_text: str
    entities: list[PIIEntity]
    redaction_map: dict[str, str] | None = None  # Original -> Anonymized mapping
    provider_metadata: dict[str, Any] | None = None


class EmbeddingResult(BaseModel):
    """Result of embedding generation."""

    embeddings: list[list[float]]  # List of embedding vectors
    model: str
    dimension: int
    usage: dict[str, int] | None = None  # {total_tokens}
    provider_metadata: dict[str, Any] | None = None


# =============================================================================
# Provider Protocols
# =============================================================================


@runtime_checkable
class TranscriptionProvider(Protocol):
    """Protocol for audio transcription providers.

    Implementers: OpenAITranscriptionProvider, DeepgramProvider,
                  AssemblyAIProvider, AccentSTTProvider
    """

    async def transcribe(
        self,
        audio: bytes | str,  # Audio bytes or URL
        language: str | None = None,
        speaker_diarization: bool = False,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: Audio data (bytes) or URL to audio file
            language: Optional language code (en, es, fr, etc.)
            speaker_diarization: Enable speaker identification
            **kwargs: Provider-specific options

        Returns:
            TranscriptionResult with text, segments, and metadata

        Raises:
            ProviderError: If transcription fails
        """
        ...

    async def transcribe_dual_channel(
        self,
        channel1: bytes | str,
        channel2: bytes | str,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe dual-channel audio (e.g., agent/customer).

        Args:
            channel1: First audio channel (typically agent)
            channel2: Second audio channel (typically customer)
            language: Optional language code
            **kwargs: Provider-specific options

        Returns:
            Merged TranscriptionResult with speaker attribution

        Raises:
            ProviderError: If transcription fails
        """
        ...

    def supports_speaker_diarization(self) -> bool:
        """Check if provider supports speaker diarization."""
        ...

    def get_supported_languages(self) -> list[str]:
        """Get list of supported language codes."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for large language model providers.

    Implementers: OpenAILLMProvider, AnthropicProvider,
                  GoogleProvider, AzureOpenAIProvider, OllamaProvider
    """

    async def generate(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate text completion from messages.

        Args:
            messages: Conversation history
            temperature: Randomness (0.0-2.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with generated text and usage

        Raises:
            ProviderError: If generation fails
        """
        ...

    async def generate_structured(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate structured output matching Pydantic model.

        Args:
            messages: Conversation history
            response_model: Pydantic model for response structure
            **kwargs: Provider-specific options

        Returns:
            Instance of response_model with parsed data

        Raises:
            ProviderError: If generation fails or parsing fails
        """
        ...

    def supports_streaming(self) -> bool:
        """Check if provider supports streaming responses."""
        ...

    def get_model_name(self) -> str:
        """Get the model name being used."""
        ...


@runtime_checkable
class PIIRedactionProvider(Protocol):
    """Protocol for PII detection and redaction.

    Implementers: AccentRedactionProvider, PresidioProvider (future)
    """

    async def detect_pii(
        self,
        text: str,
        entity_types: list[str] | None = None,
        confidence_threshold: float = 0.7,
        **kwargs: Any,
    ) -> list[PIIEntity]:
        """Detect PII entities in text.

        Args:
            text: Text to analyze
            entity_types: Specific entity types to detect (None = all)
            confidence_threshold: Minimum confidence score (0.0-1.0)
            **kwargs: Provider-specific options

        Returns:
            List of detected PII entities

        Raises:
            ProviderError: If detection fails
        """
        ...

    async def redact_pii(
        self,
        text: str,
        entity_types: list[str] | None = None,
        redaction_method: str = "mask",
        **kwargs: Any,
    ) -> PIIRedactionResult:
        """Detect and redact PII in text.

        Args:
            text: Text to redact
            entity_types: Specific entity types to redact (None = all)
            redaction_method: How to redact (mask|replace|hash|remove)
            **kwargs: Provider-specific options

        Returns:
            PIIRedactionResult with original, redacted text, and entities

        Raises:
            ProviderError: If redaction fails
        """
        ...

    def get_supported_entity_types(self) -> list[str]:
        """Get list of supported PII entity types."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers.

    Implementers: OpenAIEmbeddingProvider, CohereProvider, LocalEmbeddingProvider
    """

    async def embed(
        self,
        text: str | list[str],
        normalize: bool = True,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """Generate embeddings for text(s).

        Args:
            text: Single text or list of texts to embed
            normalize: Normalize vectors to unit length
            **kwargs: Provider-specific options

        Returns:
            EmbeddingResult with embedding vectors and metadata

        Raises:
            ProviderError: If embedding generation fails
        """
        ...

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 100,
        normalize: bool = True,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """Generate embeddings for large batches of texts.

        Automatically splits into smaller batches to respect API limits.

        Args:
            texts: List of texts to embed
            batch_size: Maximum texts per API request
            normalize: Normalize vectors to unit length
            **kwargs: Provider-specific options

        Returns:
            EmbeddingResult with all embedding vectors

        Raises:
            ProviderError: If embedding generation fails
        """
        ...

    def get_dimension(self) -> int:
        """Get the dimension of embedding vectors."""
        ...

    def get_model_name(self) -> str:
        """Get the model name being used."""
        ...


# =============================================================================
# Base Implementation with Common Functionality
# =============================================================================


class BaseProvider(ABC):
    """Base class for all AI providers with common functionality.

    Provides:
    - Error handling and retry logic
    - Usage tracking
    - Timeout management
    - Logging
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        """Initialize base provider.

        Args:
            api_key: Provider API key
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name for logging and metrics."""
        ...

    def _validate_api_key(self) -> None:
        """Validate API key is present.

        Raises:
            ValueError: If API key is missing
        """
        if not self.api_key:
            raise ValueError(
                f"{self.get_provider_name()} requires an API key. "
                "Configure via settings or tenant config."
            )


# =============================================================================
# Provider Exceptions
# =============================================================================


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        operation: str,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize provider error.

        Args:
            message: Error description
            provider: Provider name
            operation: Operation that failed
            original_error: Original exception if any
        """
        self.provider = provider
        self.operation = operation
        self.original_error = original_error
        super().__init__(message)


class ProviderAuthenticationError(ProviderError):
    """Authentication failed (invalid API key)."""


class ProviderRateLimitError(ProviderError):
    """Rate limit exceeded."""


class ProviderTimeoutError(ProviderError):
    """Request timed out."""


class ProviderInvalidInputError(ProviderError):
    """Invalid input provided to provider."""


# =============================================================================
# Provider Configuration
# =============================================================================


@dataclass
class ProviderConfig:
    """Configuration for initializing a provider.

    Used by ProviderFactory to create provider instances.
    """

    provider_name: str
    api_key: str | None = None
    model_name: str | None = None
    base_url: str | None = None  # For self-hosted services
    timeout: int = 120
    max_retries: int = 3
    additional_config: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for provider initialization."""
        config = {
            "api_key": self.api_key,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }
        if self.model_name:
            config["model_name"] = self.model_name
        if self.base_url:
            config["base_url"] = self.base_url
        if self.additional_config:
            config.update(self.additional_config)
        return config
