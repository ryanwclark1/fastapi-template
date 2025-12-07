"""Provider factory for creating AI provider instances.

Creates appropriate provider instances based on configuration:
- Resolves tenant-specific or service-level configuration
- Instantiates correct provider class
- Handles provider registration and caching
- Validates provider compatibility
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.infra.ai.config_manager import AIConfigManager
from example_service.infra.ai.providers.base import (
    LLMProvider,
    PIIRedactionProvider,
    ProviderError,
    TranscriptionProvider,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Factory for creating AI provider instances.

    Maintains registry of available providers and handles instantiation
    with proper configuration resolution.

    Usage:
        factory = ProviderFactory(session)
        provider = await factory.create_transcription_provider(
            tenant_id="tenant-123",
            provider_name="deepgram"
        )
        result = await provider.transcribe(audio_data)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize provider factory.

        Args:
            session: Database session for config resolution
        """
        self.session = session
        self.config_manager = AIConfigManager(session)
        self._transcription_registry: dict[str, type[TranscriptionProvider]] = {}
        self._llm_registry: dict[str, type[LLMProvider]] = {}
        self._pii_registry: dict[str, type[PIIRedactionProvider]] = {}

        # Register built-in providers
        self._register_builtin_providers()

    async def create_transcription_provider(
        self,
        tenant_id: str,
        provider_name: str | None = None,
    ) -> TranscriptionProvider:
        """Create transcription provider instance for tenant.

        Args:
            tenant_id: Tenant identifier
            provider_name: Optional provider override

        Returns:
            Configured transcription provider instance

        Raises:
            ProviderError: If provider creation fails
            ValueError: If provider not found or misconfigured
        """
        # Get configuration
        config = await self.config_manager.get_transcription_config(
            tenant_id, provider_name
        )

        # Get provider class
        provider_class = self._transcription_registry.get(config.provider_name)
        if not provider_class:
            raise ValueError(
                f"Transcription provider '{config.provider_name}' not found. "
                f"Available: {list(self._transcription_registry.keys())}"
            )

        # Instantiate provider
        try:
            provider = provider_class(**config.to_dict())
            logger.info(
                "Created transcription provider",
                extra={
                    "tenant_id": tenant_id,
                    "provider": config.provider_name,
                    "model": config.model_name,
                },
            )
            return provider
        except Exception as e:
            raise ProviderError(
                f"Failed to create {config.provider_name} transcription provider: {e}",
                provider=config.provider_name,
                operation="instantiation",
                original_error=e,
            ) from e

    async def create_llm_provider(
        self,
        tenant_id: str,
        provider_name: str | None = None,
    ) -> LLMProvider:
        """Create LLM provider instance for tenant.

        Args:
            tenant_id: Tenant identifier
            provider_name: Optional provider override

        Returns:
            Configured LLM provider instance

        Raises:
            ProviderError: If provider creation fails
            ValueError: If provider not found or misconfigured
        """
        # Get configuration
        config = await self.config_manager.get_llm_config(tenant_id, provider_name)

        # Get provider class
        provider_class = self._llm_registry.get(config.provider_name)
        if not provider_class:
            raise ValueError(
                f"LLM provider '{config.provider_name}' not found. "
                f"Available: {list(self._llm_registry.keys())}"
            )

        # Instantiate provider
        try:
            provider = provider_class(**config.to_dict())
            logger.info(
                "Created LLM provider",
                extra={
                    "tenant_id": tenant_id,
                    "provider": config.provider_name,
                    "model": config.model_name,
                },
            )
            return provider
        except Exception as e:
            raise ProviderError(
                f"Failed to create {config.provider_name} LLM provider: {e}",
                provider=config.provider_name,
                operation="instantiation",
                original_error=e,
            ) from e

    async def create_pii_provider(self, tenant_id: str) -> PIIRedactionProvider:
        """Create PII redaction provider instance for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Configured PII redaction provider instance

        Raises:
            ProviderError: If provider creation fails
            ValueError: If provider not found or misconfigured
        """
        # Get configuration
        config = await self.config_manager.get_pii_redaction_config(tenant_id)

        # For now, we only support accent-redaction
        provider_name = "accent_redaction"
        provider_class = self._pii_registry.get(provider_name)

        if not provider_class:
            raise ValueError(f"PII provider '{provider_name}' not found")

        # Instantiate provider
        try:
            provider = provider_class(**config)
            logger.info(
                "Created PII redaction provider",
                extra={"tenant_id": tenant_id, "provider": provider_name},
            )
            return provider
        except Exception as e:
            raise ProviderError(
                f"Failed to create {provider_name} PII provider: {e}",
                provider=provider_name,
                operation="instantiation",
                original_error=e,
            ) from e

    def register_transcription_provider(
        self,
        name: str,
        provider_class: type[TranscriptionProvider],
    ) -> None:
        """Register a transcription provider implementation.

        Args:
            name: Provider name (e.g., 'openai', 'deepgram')
            provider_class: Provider class implementing TranscriptionProvider
        """
        self._transcription_registry[name] = provider_class
        logger.debug("Registered transcription provider: %s", name)

    def register_llm_provider(
        self,
        name: str,
        provider_class: type[LLMProvider],
    ) -> None:
        """Register an LLM provider implementation.

        Args:
            name: Provider name (e.g., 'openai', 'anthropic')
            provider_class: Provider class implementing LLMProvider
        """
        self._llm_registry[name] = provider_class
        logger.debug("Registered LLM provider: %s", name)

    def register_pii_provider(
        self,
        name: str,
        provider_class: type[PIIRedactionProvider],
    ) -> None:
        """Register a PII redaction provider implementation.

        Args:
            name: Provider name (e.g., 'accent_redaction')
            provider_class: Provider class implementing PIIRedactionProvider
        """
        self._pii_registry[name] = provider_class
        logger.debug("Registered PII provider: %s", name)

    def _register_builtin_providers(self) -> None:
        """Register all built-in provider implementations.

        This is called during factory initialization to make standard
        providers available. Providers are imported lazily to avoid
        dependencies if not used.
        """
        # Import and register providers lazily
        # This avoids circular imports and dependency issues

        # Transcription providers
        try:
            from example_service.infra.ai.providers.openai_provider import (
                OpenAITranscriptionProvider,
            )

            self.register_transcription_provider("openai", OpenAITranscriptionProvider)
        except ImportError as e:
            logger.debug("OpenAI transcription provider not available: %s", e)

        try:
            from example_service.infra.ai.providers.deepgram_provider import (
                DeepgramProvider,
            )

            self.register_transcription_provider("deepgram", DeepgramProvider)
        except ImportError as e:
            logger.debug("Deepgram provider not available: %s", e)

        try:
            from example_service.infra.ai.providers.assemblyai_provider import (
                AssemblyAIProvider,
            )

            self.register_transcription_provider("assemblyai", AssemblyAIProvider)
        except ImportError as e:
            logger.debug("AssemblyAI provider not available: %s", e)

        # LLM providers
        try:
            from example_service.infra.ai.providers.openai_provider import (
                OpenAILLMProvider,
            )

            self.register_llm_provider("openai", OpenAILLMProvider)
        except ImportError as e:
            logger.debug("OpenAI LLM provider not available: %s", e)

        try:
            from example_service.infra.ai.providers.anthropic_provider import (
                AnthropicProvider,
            )

            self.register_llm_provider("anthropic", AnthropicProvider)
        except ImportError as e:
            logger.debug("Anthropic provider not available: %s", e)

        # PII providers
        try:
            from example_service.infra.ai.providers.accent_redaction_client import (
                AccentRedactionProvider,
            )

            self.register_pii_provider("accent_redaction", AccentRedactionProvider)
        except ImportError as e:
            logger.debug("Accent redaction provider not available: %s", e)

    def get_available_providers(self) -> dict[str, list[str]]:
        """Get list of available providers by type.

        Returns:
            Dictionary mapping provider type to list of provider names

        Example:
            providers = factory.get_available_providers()
            print(f"Available LLMs: {providers['llm']}")
            print(f"Available transcription: {providers['transcription']}")
        """
        return {
            "transcription": list(self._transcription_registry.keys()),
            "llm": list(self._llm_registry.keys()),
            "pii_redaction": list(self._pii_registry.keys()),
        }

    def get_default_providers(self) -> dict[str, str]:
        """Get default provider names from settings.

        Returns service-level default providers. For tenant-specific defaults,
        use the config_manager to resolve tenant configuration.

        Returns:
            Dictionary with default provider names by type

        Example:
            defaults = factory.get_default_providers()
            print(f"Default LLM: {defaults['llm']}")
            print(f"Default transcription: {defaults['transcription']}")
        """
        return {
            "llm": self.config_manager.settings.default_llm_provider,
            "transcription": self.config_manager.settings.default_transcription_provider,
            "embedding": self.config_manager.settings.default_embedding_provider,
            "pii_redaction": "accent_redaction",  # Only one supported for now
        }

    def reset_registries(self) -> None:
        """Reset all provider registries.

        Useful for testing or when you need to re-register providers.
        This does NOT close any active provider instances - those should be
        managed by the application.

        Warning:
            This will clear all registered providers including built-in ones.
            Call _register_builtin_providers() afterward if you want them back.

        Example:
            # In tests
            factory.reset_registries()
            factory._register_builtin_providers()
        """
        self._transcription_registry.clear()
        self._llm_registry.clear()
        self._pii_registry.clear()
        logger.info("Reset all provider registries")


# ===== Module-level Utility Functions =====
# These provide simplified access for testing and simple use cases


# Global factory instance cache (keyed by session ID to support multiple tenants)
_factory_instances: dict[int, ProviderFactory] = {}


def get_factory(session: AsyncSession) -> ProviderFactory:
    """Get or create a ProviderFactory instance for a session.

    Caches factory instances per session to avoid re-registration overhead.

    Args:
        session: Database session

    Returns:
        ProviderFactory instance

    Example:
        async with get_session() as session:
            factory = get_factory(session)
            provider = await factory.create_llm_provider("tenant-123")
    """
    session_id = id(session)
    if session_id not in _factory_instances:
        _factory_instances[session_id] = ProviderFactory(session)
    return _factory_instances[session_id]


def get_available_providers() -> dict[str, list[str]]:
    """Get list of available provider types.

    Returns statically registered providers without requiring a session.
    For dynamic provider lists based on configuration, use a ProviderFactory instance.

    Returns:
        Dictionary mapping provider type to list of provider names

    Example:
        providers = get_available_providers()
        print(f"Available LLMs: {providers['llm']}")
    """
    # Return static list of known providers
    # This doesn't require a session or factory instance
    return {
        "transcription": ["openai", "deepgram", "assemblyai", "accent_stt"],
        "llm": ["openai", "anthropic", "google", "azure_openai", "ollama"],
        "pii_redaction": ["accent_redaction"],
    }


def get_default_providers() -> dict[str, str]:
    """Get default provider names from settings.

    Returns service-level defaults without requiring a session.
    For tenant-specific defaults, use a ProviderFactory instance.

    Returns:
        Dictionary with default provider names by type

    Example:
        defaults = get_default_providers()
        print(f"Default LLM: {defaults['llm']}")
    """
    from example_service.core.settings import get_ai_settings

    settings = get_ai_settings()
    return {
        "llm": settings.default_llm_provider,
        "transcription": settings.default_transcription_provider,
        "embedding": settings.default_embedding_provider,
        "pii_redaction": "accent_redaction",
    }


def reset_factories() -> None:
    """Clear all cached factory instances.

    Useful for testing or when you need to recreate factories with
    fresh registries.

    Warning:
        This does not close any active provider instances.
        Make sure to properly cleanup providers before calling this.

    Example:
        # In tests
        reset_factories()
    """
    _factory_instances.clear()
    logger.info("Reset all cached factory instances")


async def close_all_providers() -> None:
    """Close all provider instances across all cached factories.

    This is a best-effort cleanup function. Since providers are created
    on-demand and may not have cleanup methods, this primarily clears
    the factory cache.

    For production use, ensure each provider instance is properly closed
    when no longer needed, rather than relying on this global cleanup.

    Example:
        # At application shutdown
        await close_all_providers()
    """
    logger.info("Closing all AI provider instances")

    # Clear factory instances
    # Note: Individual providers created by factories are not tracked here
    # The application should manage provider lifecycle per-request/per-tenant
    _factory_instances.clear()

    logger.info(
        "Cleared factory cache. Individual provider cleanup should be managed per-request."
    )
