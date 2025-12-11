"""AI provider implementations.

Provides abstraction layer for AI services:
- Transcription providers (OpenAI Whisper, Deepgram, AssemblyAI, accent-stt)
- LLM providers (OpenAI, Anthropic, Google, Azure OpenAI, Ollama)
- Embedding providers (OpenAI, Cohere, local models)
- PII redaction service client (accent-redaction)
- Provider factory with tenant-aware configuration resolution

Usage:
    # Using the factory directly
    from example_service.infra.ai.providers import get_factory
    async with get_session() as session:
        factory = get_factory(session)
        provider = await factory.create_llm_provider("tenant-123")

    # Using providers directly
    from example_service.infra.ai.providers import OpenAIEmbeddingProvider
    provider = OpenAIEmbeddingProvider(api_key="sk-...")
    result = await provider.embed("Hello, world!")

    # Using utility functions
    from example_service.infra.ai.providers import (
        get_available_providers,
        get_default_providers,
    )
    print(get_available_providers())
    print(get_default_providers())
"""

from __future__ import annotations

from .base import (
    BaseProvider,
    EmbeddingProvider,
    EmbeddingResult,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    PIIEntity,
    PIIRedactionProvider,
    PIIRedactionResult,
    ProviderAuthenticationError,
    ProviderConfig,
    ProviderError,
    ProviderInvalidInputError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegment,
)
from .factory import (
    ProviderFactory,
    close_all_providers,
    get_available_providers,
    get_default_providers,
    get_factory,
    reset_factories,
)
from .openai_provider import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
    OpenAITranscriptionProvider,
)

__all__ = [
    # Base classes and protocols
    "BaseProvider",
    "EmbeddingProvider",
    "EmbeddingResult",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "OpenAIEmbeddingProvider",
    "OpenAILLMProvider",
    # OpenAI implementations
    "OpenAITranscriptionProvider",
    "PIIEntity",
    "PIIRedactionProvider",
    "PIIRedactionResult",
    "ProviderAuthenticationError",
    # Configuration
    "ProviderConfig",
    # Exceptions
    "ProviderError",
    # Main factory class
    "ProviderFactory",
    "ProviderInvalidInputError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "TranscriptionProvider",
    # Result models
    "TranscriptionResult",
    "TranscriptionSegment",
    "close_all_providers",
    "get_available_providers",
    "get_default_providers",
    # Utility functions
    "get_factory",
    "reset_factories",
]
