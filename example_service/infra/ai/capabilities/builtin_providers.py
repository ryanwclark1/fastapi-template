"""Built-in provider registration for the capability system.

This module registers all built-in AI providers with the capability registry.
Providers include:
- OpenAI (LLM, transcription)
- Anthropic (LLM, specialized analysis)
- Deepgram (transcription, diarization)
- Accent Redaction (internal PII service)

Registration happens at application startup via register_builtin_providers().

Configuration:
    Providers are configured via AISettings. Each provider can be:
    - Enabled/disabled globally
    - Configured with API keys and model preferences
    - Overridden per-tenant via TenantAIConfig

Example:
    # In your application startup
    from example_service.infra.ai.capabilities.builtin_providers import (
        register_builtin_providers,
    )
    from example_service.infra.ai.capabilities.registry import get_capability_registry

    registry = get_capability_registry()
    register_builtin_providers(registry, settings)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.capabilities.registry import (
    CapabilityRegistry,
    get_capability_registry,
)

if TYPE_CHECKING:
    from example_service.core.settings.ai import AISettings
    from example_service.infra.ai.capabilities.adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)


# Provider factory functions
# These create adapter instances with configuration


def create_openai_adapter(
    api_key: str | None = None,
    model_name: str | None = None,
    transcription_model: str | None = None,
    timeout: int = 120,
    max_retries: int = 3,
    **kwargs: Any,
) -> ProviderAdapter:
    """Create an OpenAI adapter instance.

    Args:
        api_key: OpenAI API key (required)
        model_name: LLM model to use (default: gpt-4o-mini)
        transcription_model: Whisper model (default: whisper-1)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts

    Returns:
        Configured OpenAIAdapter instance

    Raises:
        ValueError: If api_key is not provided
    """
    if not api_key:
        raise ValueError("OpenAI API key is required")

    from example_service.infra.ai.capabilities.adapters.openai import OpenAIAdapter

    return OpenAIAdapter(
        api_key=api_key,
        model_name=model_name or "gpt-4o-mini",
        transcription_model=transcription_model or "whisper-1",
        timeout=timeout,
        max_retries=max_retries,
        **kwargs,
    )


def create_anthropic_adapter(
    api_key: str | None = None,
    model_name: str | None = None,
    timeout: int = 120,
    max_retries: int = 3,
    **kwargs: Any,
) -> ProviderAdapter:
    """Create an Anthropic adapter instance.

    Args:
        api_key: Anthropic API key (required)
        model_name: Model to use (default: claude-sonnet-4-20250514)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts

    Returns:
        Configured AnthropicAdapter instance

    Raises:
        ValueError: If api_key is not provided
    """
    if not api_key:
        raise ValueError("Anthropic API key is required")

    from example_service.infra.ai.capabilities.adapters.anthropic import (
        AnthropicAdapter,
    )

    return AnthropicAdapter(
        api_key=api_key,
        model_name=model_name or "claude-sonnet-4-20250514",
        timeout=timeout,
        max_retries=max_retries,
        **kwargs,
    )


def create_deepgram_adapter(
    api_key: str | None = None,
    model_name: str | None = None,
    timeout: int = 120,
    max_retries: int = 3,
    **kwargs: Any,
) -> ProviderAdapter:
    """Create a Deepgram adapter instance.

    Args:
        api_key: Deepgram API key (required)
        model_name: Model to use (default: nova-2)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts

    Returns:
        Configured DeepgramAdapter instance

    Raises:
        ValueError: If api_key is not provided
    """
    if not api_key:
        raise ValueError("Deepgram API key is required")

    from example_service.infra.ai.capabilities.adapters.deepgram import DeepgramAdapter

    return DeepgramAdapter(
        api_key=api_key,
        model_name=model_name or "nova-2",
        timeout=timeout,
        max_retries=max_retries,
        **kwargs,
    )


def create_accent_redaction_adapter(
    api_key: str | None = None,
    service_url: str | None = None,
    entity_types: list[str] | None = None,
    confidence_threshold: float = 0.7,
    timeout: int = 60,
    **kwargs: Any,
) -> ProviderAdapter:
    """Create an Accent Redaction adapter instance.

    Args:
        api_key: Optional API key (for external deployments)
        service_url: URL of accent-redaction service
        entity_types: Default entity types to detect
        confidence_threshold: Minimum confidence (0.0-1.0)
        timeout: Request timeout in seconds

    Returns:
        Configured AccentRedactionAdapter instance
    """
    from example_service.infra.ai.capabilities.adapters.accent_redaction import (
        AccentRedactionAdapter,
    )

    return AccentRedactionAdapter(
        api_key=api_key,
        service_url=service_url or "http://accent-redaction:8502",
        entity_types=entity_types,
        confidence_threshold=confidence_threshold,
        timeout=timeout,
        **kwargs,
    )


# Provider registration functions


def _register_openai(
    registry: CapabilityRegistry,
    api_key: str,
    model_name: str = "gpt-4o-mini",
    transcription_model: str = "whisper-1",
    **_kwargs: Any,
) -> None:
    """Register OpenAI provider with the registry.

    Creates a temporary adapter to get the registration, then stores
    the factory function for later instantiation.
    """
    from example_service.infra.ai.capabilities.adapters.openai import OpenAIAdapter

    # Create a temporary adapter to get the registration
    temp_adapter = OpenAIAdapter(
        api_key=api_key,
        model_name=model_name,
        transcription_model=transcription_model,
    )

    registration = temp_adapter.get_registration()

    registry.register_provider(
        registration,
        adapter_factory=create_openai_adapter,
    )

    logger.info(
        "Registered OpenAI provider",
        extra={
            "model": model_name,
            "transcription_model": transcription_model,
        },
    )


def _register_anthropic(
    registry: CapabilityRegistry,
    api_key: str,
    model_name: str = "claude-sonnet-4-20250514",
    **_kwargs: Any,
) -> None:
    """Register Anthropic provider with the registry."""
    from example_service.infra.ai.capabilities.adapters.anthropic import (
        AnthropicAdapter,
    )

    temp_adapter = AnthropicAdapter(
        api_key=api_key,
        model_name=model_name,
    )

    registration = temp_adapter.get_registration()

    registry.register_provider(
        registration,
        adapter_factory=create_anthropic_adapter,
    )

    logger.info(
        "Registered Anthropic provider",
        extra={"model": model_name},
    )


def _register_deepgram(
    registry: CapabilityRegistry,
    api_key: str,
    model_name: str = "nova-2",
    **_kwargs: Any,
) -> None:
    """Register Deepgram provider with the registry."""
    from example_service.infra.ai.capabilities.adapters.deepgram import DeepgramAdapter

    temp_adapter = DeepgramAdapter(
        api_key=api_key,
        model_name=model_name,
    )

    registration = temp_adapter.get_registration()

    registry.register_provider(
        registration,
        adapter_factory=create_deepgram_adapter,
    )

    logger.info(
        "Registered Deepgram provider",
        extra={"model": model_name},
    )


def _register_accent_redaction(
    registry: CapabilityRegistry,
    service_url: str = "http://accent-redaction:8502",
    **_kwargs: Any,
) -> None:
    """Register Accent Redaction provider with the registry."""
    from example_service.infra.ai.capabilities.adapters.accent_redaction import (
        AccentRedactionAdapter,
    )

    temp_adapter = AccentRedactionAdapter(
        service_url=service_url,
    )

    registration = temp_adapter.get_registration()

    registry.register_provider(
        registration,
        adapter_factory=create_accent_redaction_adapter,
    )

    logger.info(
        "Registered Accent Redaction provider",
        extra={"service_url": service_url},
    )


def register_builtin_providers(
    registry: CapabilityRegistry | None = None,
    settings: AISettings | None = None,
    *,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    deepgram_api_key: str | None = None,
    accent_redaction_url: str | None = None,
    skip_unavailable: bool = True,
) -> dict[str, bool]:
    """Register all built-in AI providers with the capability registry.

    This function should be called at application startup to register
    all available providers. Providers without API keys can be skipped
    or will raise errors based on skip_unavailable.

    Args:
        registry: CapabilityRegistry instance (uses global if None)
        settings: AISettings instance for configuration
        openai_api_key: Override OpenAI API key
        anthropic_api_key: Override Anthropic API key
        deepgram_api_key: Override Deepgram API key
        accent_redaction_url: Override accent-redaction service URL
        skip_unavailable: Skip providers without credentials (default: True)

    Returns:
        Dict mapping provider names to registration success status

    Example:
        # Register from settings
        status = register_builtin_providers(settings=ai_settings)

        # Register with explicit keys
        status = register_builtin_providers(
            openai_api_key="sk-...",
            anthropic_api_key="sk-ant-...",
            deepgram_api_key="...",
        )

        # Check what was registered
        print(status)
        # {'openai': True, 'anthropic': True, 'deepgram': False, 'accent_redaction': True}
    """
    if registry is None:
        registry = get_capability_registry()

    # Extract configuration from settings if provided
    if settings:
        openai_api_key = openai_api_key or getattr(settings, "openai_api_key", None)
        anthropic_api_key = anthropic_api_key or getattr(settings, "anthropic_api_key", None)
        deepgram_api_key = deepgram_api_key or getattr(settings, "deepgram_api_key", None)
        accent_redaction_url = accent_redaction_url or getattr(
            settings, "accent_redaction_url", "http://accent-redaction:8502"
        )

    results: dict[str, bool] = {}

    # Register OpenAI
    if openai_api_key:
        try:
            _register_openai(
                registry,
                api_key=openai_api_key,
                model_name=getattr(settings, "openai_model", "gpt-4o-mini")
                if settings
                else "gpt-4o-mini",
                transcription_model=(
                    getattr(settings, "openai_transcription_model", "whisper-1")
                    if settings
                    else "whisper-1"
                ),
            )
            results["openai"] = True
        except Exception as e:
            logger.error(f"Failed to register OpenAI provider: {e}")
            results["openai"] = False
    elif not skip_unavailable:
        logger.warning("OpenAI API key not provided, skipping registration")
        results["openai"] = False
    else:
        results["openai"] = False

    # Register Anthropic
    if anthropic_api_key:
        try:
            _register_anthropic(
                registry,
                api_key=anthropic_api_key,
                model_name=(
                    getattr(settings, "anthropic_model", "claude-sonnet-4-20250514")
                    if settings
                    else "claude-sonnet-4-20250514"
                ),
            )
            results["anthropic"] = True
        except Exception as e:
            logger.error(f"Failed to register Anthropic provider: {e}")
            results["anthropic"] = False
    elif not skip_unavailable:
        logger.warning("Anthropic API key not provided, skipping registration")
        results["anthropic"] = False
    else:
        results["anthropic"] = False

    # Register Deepgram
    if deepgram_api_key:
        try:
            _register_deepgram(
                registry,
                api_key=deepgram_api_key,
                model_name=getattr(settings, "deepgram_model", "nova-2") if settings else "nova-2",
            )
            results["deepgram"] = True
        except Exception as e:
            logger.error(f"Failed to register Deepgram provider: {e}")
            results["deepgram"] = False
    elif not skip_unavailable:
        logger.warning("Deepgram API key not provided, skipping registration")
        results["deepgram"] = False
    else:
        results["deepgram"] = False

    # Register Accent Redaction (internal service, no API key required)
    try:
        _register_accent_redaction(
            registry,
            service_url=accent_redaction_url or "http://accent-redaction:8502",
        )
        results["accent_redaction"] = True
    except Exception as e:
        logger.error(f"Failed to register Accent Redaction provider: {e}")
        results["accent_redaction"] = False

    # Summary logging
    registered = [name for name, success in results.items() if success]
    failed = [name for name, success in results.items() if not success]

    logger.info(
        f"Provider registration complete: {len(registered)} registered, {len(failed)} skipped/failed",
        extra={
            "registered_providers": registered,
            "failed_providers": failed,
        },
    )

    return results


def get_provider_info() -> dict[str, dict[str, Any]]:
    """Get information about all available built-in providers.

    Returns metadata about each provider including:
    - Description
    - Required credentials
    - Supported capabilities
    - Pricing information

    Returns:
        Dict mapping provider names to their metadata

    Example:
        info = get_provider_info()
        print(info["openai"]["capabilities"])
    """
    return {
        "openai": {
            "name": "OpenAI",
            "description": "GPT models for text generation and Whisper for transcription",
            "provider_type": "external",
            "requires_api_key": True,
            "capabilities": [
                "llm_generation",
                "llm_structured",
                "llm_streaming",
                "transcription",
                "transcription_dual_channel",
            ],
            "pricing_url": "https://openai.com/pricing",
            "documentation_url": "https://platform.openai.com/docs",
            "default_models": {
                "llm": "gpt-4o-mini",
                "transcription": "whisper-1",
            },
        },
        "anthropic": {
            "name": "Anthropic",
            "description": "Claude models for text generation and specialized analysis",
            "provider_type": "external",
            "requires_api_key": True,
            "capabilities": [
                "llm_generation",
                "llm_structured",
                "llm_streaming",
                "summarization",
                "sentiment_analysis",
                "coaching_analysis",
            ],
            "pricing_url": "https://www.anthropic.com/pricing",
            "documentation_url": "https://docs.anthropic.com",
            "default_models": {
                "llm": "claude-sonnet-4-20250514",
            },
        },
        "deepgram": {
            "name": "Deepgram",
            "description": "Nova-2 model for high-accuracy transcription with speaker diarization",
            "provider_type": "external",
            "requires_api_key": True,
            "capabilities": [
                "transcription",
                "transcription_diarization",
                "transcription_dual_channel",
            ],
            "pricing_url": "https://deepgram.com/pricing",
            "documentation_url": "https://developers.deepgram.com/docs",
            "default_models": {
                "transcription": "nova-2",
            },
        },
        "accent_redaction": {
            "name": "Accent Redaction",
            "description": "Internal service for PII detection and redaction",
            "provider_type": "internal",
            "requires_api_key": False,
            "capabilities": [
                "pii_detection",
                "pii_redaction",
            ],
            "pricing_url": None,
            "documentation_url": None,
            "default_models": {},
            "notes": "Zero cost internal service with highest priority for PII operations",
        },
    }
