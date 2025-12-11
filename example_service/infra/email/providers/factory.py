"""Email provider factory with lazy registration.

Provides centralized provider management with:
- Lazy provider registration (optional dependencies)
- Provider caching per configuration
- Runtime provider discovery
- Graceful degradation for unavailable providers

Usage:
    factory = get_provider_factory()

    # Get provider for a resolved config
    provider = factory.get_provider(config)
    result = await provider.send(message)

    # List available providers
    providers = factory.list_providers()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.core.models.email_config import EmailProviderType

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig

    from .base import BaseEmailProvider, EmailProvider

logger = logging.getLogger(__name__)


class EmailProviderFactory:
    """Factory for creating and caching email providers.

    Features:
    - Lazy provider registration (optional dependencies loaded on demand)
    - Provider caching to avoid recreating providers
    - Graceful degradation when optional providers unavailable
    - Runtime provider discovery

    Example:
        factory = EmailProviderFactory()

        # Get provider for resolved config
        provider = factory.get_provider(config)

        # Check available providers
        available = factory.list_providers()
        print(f"Available: {available}")
    """

    def __init__(self) -> None:
        """Initialize factory with builtin providers."""
        self._registry: dict[str, type[BaseEmailProvider]] = {}
        self._provider_cache: dict[str, EmailProvider] = {}
        self._unavailable: dict[str, str] = {}  # provider -> reason

        # Register builtin providers
        self._register_builtin_providers()

    def _register_builtin_providers(self) -> None:
        """Register providers that are always available."""
        # SMTP - always available (uses aiosmtplib)
        from .smtp import SMTPProvider

        self.register("smtp", SMTPProvider)

        # Console - always available (no external deps)
        from .console import ConsoleProvider

        self.register("console", ConsoleProvider)

        # File - always available (no external deps)
        from .file import FileProvider

        self.register("file", FileProvider)

        # Try to register optional providers
        self._try_register_optional_providers()

    def _try_register_optional_providers(self) -> None:
        """Try to register providers with optional dependencies."""
        # AWS SES - requires aioboto3
        try:
            from .ses import SESProvider

            self.register("aws_ses", SESProvider)
            logger.debug("AWS SES provider registered")
        except ImportError as e:
            self._unavailable["aws_ses"] = f"aioboto3 not installed: {e}"
            logger.info("AWS SES provider not available (install aioboto3)")

        # SendGrid - uses httpx (already in project)
        try:
            from .sendgrid import SendGridProvider

            self.register("sendgrid", SendGridProvider)
            logger.debug("SendGrid provider registered")
        except ImportError as e:
            self._unavailable["sendgrid"] = f"httpx not installed: {e}"
            logger.info("SendGrid provider not available")

        # Mailgun - uses httpx (already in project)
        try:
            from .mailgun import MailgunProvider

            self.register("mailgun", MailgunProvider)
            logger.debug("Mailgun provider registered")
        except ImportError as e:
            self._unavailable["mailgun"] = f"httpx not installed: {e}"
            logger.info("Mailgun provider not available")

    def register(
        self,
        provider_type: str,
        provider_class: type[BaseEmailProvider],
    ) -> None:
        """Register a provider class.

        Args:
            provider_type: Provider type identifier (e.g., "smtp", "sendgrid")
            provider_class: Provider class to register
        """
        self._registry[provider_type] = provider_class
        # Remove from unavailable if it was there
        self._unavailable.pop(provider_type, None)
        logger.debug("Registered email provider: %s", provider_type)

    def unregister(self, provider_type: str) -> bool:
        """Unregister a provider.

        Args:
            provider_type: Provider type to unregister

        Returns:
            True if provider was registered and removed
        """
        if provider_type in self._registry:
            del self._registry[provider_type]
            # Also clear any cached instances
            self._clear_cache_for_provider(provider_type)
            logger.debug("Unregistered email provider: %s", provider_type)
            return True
        return False

    def get_provider(self, config: ResolvedEmailConfig) -> EmailProvider:
        """Get or create a provider for the given configuration.

        Providers are cached by a key derived from the configuration
        to avoid recreating them for the same settings.

        Args:
            config: Resolved email configuration

        Returns:
            EmailProvider instance

        Raises:
            ValueError: If provider type is not registered
        """
        provider_type = config.provider_type.value

        # Check if provider is registered
        if provider_type not in self._registry:
            if provider_type in self._unavailable:
                msg = (
                    f"Provider '{provider_type}' is not available: "
                    f"{self._unavailable[provider_type]}"
                )
                raise ValueError(
                    msg,
                )
            msg = (
                f"Unknown provider type: {provider_type}. "
                f"Available: {list(self._registry.keys())}"
            )
            raise ValueError(
                msg,
            )

        # Create cache key from config
        cache_key = self._make_cache_key(config)

        # Return cached provider if available
        if cache_key in self._provider_cache:
            logger.debug(
                f"Using cached {provider_type} provider",
                extra={"tenant_id": config.tenant_id},
            )
            return self._provider_cache[cache_key]

        # Create new provider
        provider_class = self._registry[provider_type]
        provider = provider_class(config)

        # Cache it
        self._provider_cache[cache_key] = provider
        logger.debug(
            f"Created new {provider_type} provider",
            extra={"tenant_id": config.tenant_id},
        )

        return provider

    def _make_cache_key(self, config: ResolvedEmailConfig) -> str:
        """Create a cache key from configuration.

        The key should change if any configuration that affects
        provider behavior changes.

        Args:
            config: Resolved configuration

        Returns:
            Cache key string
        """
        # Include tenant_id and provider type
        # For tenant configs, include source to differentiate
        parts = [
            config.provider_type.value,
            config.tenant_id or "system",
            config.source,
        ]

        # Add provider-specific identifiers
        if config.provider_type == EmailProviderType.SMTP:
            parts.extend([
                config.smtp_host or "",
                str(config.smtp_port or ""),
                config.smtp_username or "",
            ])
        elif config.provider_type == EmailProviderType.AWS_SES:
            parts.extend([
                config.aws_region or "",
            ])
        elif config.provider_type in (
            EmailProviderType.SENDGRID,
            EmailProviderType.MAILGUN,
        ):
            parts.extend([
                config.api_endpoint or "",
            ])

        return ":".join(parts)

    def _clear_cache_for_provider(self, provider_type: str) -> int:
        """Clear cached providers of a specific type.

        Args:
            provider_type: Provider type to clear

        Returns:
            Number of entries cleared
        """
        keys_to_remove = [
            key for key in self._provider_cache if key.startswith(f"{provider_type}:")
        ]
        for key in keys_to_remove:
            del self._provider_cache[key]
        return len(keys_to_remove)

    def invalidate_cache(self, tenant_id: str | None = None) -> int:
        """Invalidate cached providers.

        Args:
            tenant_id: If provided, only clear cache for this tenant.
                      If None, clear all cached providers.

        Returns:
            Number of entries cleared
        """
        if tenant_id is None:
            count = len(self._provider_cache)
            self._provider_cache.clear()
            logger.info("Cleared all provider cache (%s entries)", count)
            return count

        # Clear only entries for this tenant
        keys_to_remove = [
            key for key in self._provider_cache if f":{tenant_id}:" in key
        ]
        for key in keys_to_remove:
            del self._provider_cache[key]

        if keys_to_remove:
            logger.info(
                f"Cleared provider cache for tenant {tenant_id} ({len(keys_to_remove)} entries)",
            )
        return len(keys_to_remove)

    def list_providers(self) -> list[str]:
        """List all registered providers.

        Returns:
            List of registered provider type names
        """
        return list(self._registry.keys())

    def list_unavailable(self) -> dict[str, str]:
        """List unavailable providers and reasons.

        Returns:
            Dict mapping provider name to unavailability reason
        """
        return dict(self._unavailable)

    def is_available(self, provider_type: str) -> bool:
        """Check if a provider type is available.

        Args:
            provider_type: Provider type to check

        Returns:
            True if provider is registered and available
        """
        return provider_type in self._registry

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        # Count providers by type
        by_type: dict[str, int] = {}
        for key in self._provider_cache:
            provider_type = key.split(":")[0]
            by_type[provider_type] = by_type.get(provider_type, 0) + 1

        return {
            "total_cached": len(self._provider_cache),
            "by_type": by_type,
            "registered_providers": list(self._registry.keys()),
            "unavailable_providers": list(self._unavailable.keys()),
        }


# Module-level singleton
_factory: EmailProviderFactory | None = None


def get_provider_factory() -> EmailProviderFactory:
    """Get the singleton provider factory.

    Returns:
        EmailProviderFactory instance

    Raises:
        RuntimeError: If factory not initialized
    """
    global _factory
    if _factory is None:
        msg = (
            "Email provider factory not initialized. "
            "Call initialize_provider_factory() during app startup."
        )
        raise RuntimeError(msg)
    return _factory


def initialize_provider_factory() -> EmailProviderFactory:
    """Initialize the singleton provider factory.

    Call this during application startup.

    Returns:
        Initialized EmailProviderFactory
    """
    global _factory
    _factory = EmailProviderFactory()
    logger.info(
        "Email provider factory initialized",
        extra={
            "available_providers": _factory.list_providers(),
            "unavailable_providers": list(_factory.list_unavailable().keys()),
        },
    )
    return _factory


__all__ = [
    "EmailProviderFactory",
    "get_provider_factory",
    "initialize_provider_factory",
]
