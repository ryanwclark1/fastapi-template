"""Capability Registry for AI provider discovery and routing.

The CapabilityRegistry is the central hub for:
- Registering providers with their capabilities
- Discovering providers by capability
- Building fallback chains for resilience
- Cost-aware provider selection
- Tenant-specific provider preferences

Architecture:
    CapabilityRegistry (singleton)
        ├── Provider Registrations (OpenAI, Anthropic, Deepgram, etc.)
        ├── Capability Index (capability -> [provider_names])
        └── Adapter Factories (provider_name -> factory_fn)

Usage:
    registry = get_capability_registry()

    # Register a provider
    registry.register_provider(
        ProviderRegistration(
            provider_name="deepgram",
            provider_type=ProviderType.EXTERNAL,
            capabilities=[...],
        ),
        adapter_factory=DeepgramAdapter,
    )

    # Find providers for a capability
    providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)

    # Build fallback chain
    chain = registry.build_fallback_chain(
        Capability.TRANSCRIPTION,
        primary_provider="deepgram",
        max_fallbacks=3,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.capabilities.types import (
    Capability,
    CapabilityMetadata,
    ProviderRegistration,
    QualityTier,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from example_service.infra.ai.capabilities.adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Central registry for AI provider capabilities.

    The registry maintains:
    - Provider registrations with full metadata
    - Capability-to-provider index for fast lookups
    - Adapter factory functions for lazy instantiation

    Thread Safety:
        The registry is designed to be used as a singleton.
        Provider registration should happen at startup.
        Runtime operations (get_providers, build_fallback_chain) are read-only.

    Example:
        registry = get_capability_registry()

        # Discover providers
        providers = registry.get_providers_for_capability(
            Capability.TRANSCRIPTION_DIARIZATION,
            quality_tier=QualityTier.PREMIUM,
        )

        # Get cheapest option
        cheapest = registry.get_cheapest_provider(
            Capability.LLM_GENERATION,
            min_quality_tier=QualityTier.STANDARD,
        )

        # Build resilient fallback chain
        chain = registry.build_fallback_chain(
            Capability.TRANSCRIPTION,
            primary_provider="deepgram",
            max_fallbacks=3,
        )
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[str, ProviderRegistration] = {}
        self._capability_index: dict[Capability, list[str]] = {}
        self._adapter_factories: dict[str, Callable[..., ProviderAdapter]] = {}
        self._initialized = False

    def register_provider(
        self,
        registration: ProviderRegistration,
        adapter_factory: Callable[..., ProviderAdapter] | None = None,
    ) -> None:
        """Register a provider with its capabilities.

        Args:
            registration: Provider registration with capability metadata
            adapter_factory: Optional factory function to create adapter instances

        Raises:
            ValueError: If provider is already registered
        """
        name = registration.provider_name

        if name in self._providers:
            logger.warning(
                f"Provider '{name}' already registered, updating registration",
                extra={"provider": name},
            )

        # Store registration
        self._providers[name] = registration

        # Update capability index
        for cap_meta in registration.capabilities:
            cap = cap_meta.capability
            if cap not in self._capability_index:
                self._capability_index[cap] = []
            if name not in self._capability_index[cap]:
                self._capability_index[cap].append(name)

        # Store adapter factory
        if adapter_factory:
            self._adapter_factories[name] = adapter_factory

        logger.info(
            f"Registered provider: {name}",
            extra={
                "provider": name,
                "provider_type": registration.provider_type.value,
                "capabilities": [c.capability.value for c in registration.capabilities],
            },
        )

    def unregister_provider(self, provider_name: str) -> bool:
        """Remove a provider from the registry.

        Args:
            provider_name: Name of provider to remove

        Returns:
            True if provider was removed, False if not found
        """
        if provider_name not in self._providers:
            return False

        registration = self._providers.pop(provider_name)

        # Remove from capability index
        for cap_meta in registration.capabilities:
            cap = cap_meta.capability
            if cap in self._capability_index and provider_name in self._capability_index[cap]:
                self._capability_index[cap].remove(provider_name)

        # Remove adapter factory
        self._adapter_factories.pop(provider_name, None)

        logger.info(f"Unregistered provider: {provider_name}")
        return True

    def get_provider(self, provider_name: str) -> ProviderRegistration | None:
        """Get registration for a specific provider.

        Args:
            provider_name: Name of the provider

        Returns:
            ProviderRegistration if found, None otherwise
        """
        return self._providers.get(provider_name)

    def get_providers_for_capability(
        self,
        capability: Capability,
        *,
        quality_tier: QualityTier | None = None,
        exclude_providers: list[str] | None = None,
        only_available: bool = True,
    ) -> list[ProviderRegistration]:
        """Get all providers that offer a capability.

        Results are sorted by priority (lower = higher priority).

        Args:
            capability: The capability to search for
            quality_tier: Optional filter by quality tier
            exclude_providers: Provider names to exclude
            only_available: Only include currently available providers

        Returns:
            List of ProviderRegistrations, sorted by priority
        """
        exclude = set(exclude_providers or [])
        provider_names = self._capability_index.get(capability, [])

        results = []
        for name in provider_names:
            if name in exclude:
                continue

            registration = self._providers.get(name)
            if not registration:
                continue

            if only_available and not registration.is_available:
                continue

            cap_meta = registration.get_capability(capability)
            if not cap_meta:
                continue

            if quality_tier and cap_meta.quality_tier != quality_tier:
                continue

            results.append((cap_meta.priority, registration))

        # Sort by priority (lower = higher priority)
        results.sort(key=lambda x: x[0])
        return [reg for _, reg in results]

    def get_capability_metadata(
        self,
        capability: Capability,
        provider_name: str,
    ) -> CapabilityMetadata | None:
        """Get capability metadata for a specific provider.

        Args:
            capability: The capability to look up
            provider_name: The provider name

        Returns:
            CapabilityMetadata if found, None otherwise
        """
        registration = self._providers.get(provider_name)
        if not registration:
            return None
        return registration.get_capability(capability)

    def get_cheapest_provider(
        self,
        capability: Capability,
        *,
        min_quality_tier: QualityTier = QualityTier.ECONOMY,
        exclude_providers: list[str] | None = None,
    ) -> str | None:
        """Get the cheapest provider for a capability.

        Args:
            capability: The capability needed
            min_quality_tier: Minimum acceptable quality tier
            exclude_providers: Provider names to exclude

        Returns:
            Provider name if found, None otherwise
        """
        exclude = set(exclude_providers or [])
        quality_order = {QualityTier.ECONOMY: 0, QualityTier.STANDARD: 1, QualityTier.PREMIUM: 2}
        min_quality_level = quality_order.get(min_quality_tier, 0)

        cheapest: tuple[float, str] | None = None

        for name in self._capability_index.get(capability, []):
            if name in exclude:
                continue

            registration = self._providers.get(name)
            if not registration or not registration.is_available:
                continue

            cap_meta = registration.get_capability(capability)
            if not cap_meta:
                continue

            # Check quality tier
            tier_level = quality_order.get(cap_meta.quality_tier, 0)
            if tier_level < min_quality_level:
                continue

            cost = float(cap_meta.cost_per_unit)
            if cheapest is None or cost < cheapest[0]:
                cheapest = (cost, name)

        return cheapest[1] if cheapest else None

    def build_fallback_chain(
        self,
        capability: Capability,
        primary_provider: str | None = None,
        max_fallbacks: int = 3,
        *,
        exclude_providers: list[str] | None = None,
        prefer_same_quality: bool = True,
    ) -> list[str]:
        """Build an ordered fallback chain for a capability.

        The chain includes:
        1. Primary provider (if specified and available)
        2. Other providers sorted by priority

        Args:
            capability: The capability needed
            primary_provider: Preferred provider (tried first)
            max_fallbacks: Maximum number of fallbacks after primary
            exclude_providers: Provider names to exclude
            prefer_same_quality: Try to use same quality tier for fallbacks

        Returns:
            Ordered list of provider names to try
        """
        exclude = set(exclude_providers or [])
        chain: list[str] = []

        # Add primary provider first if specified and valid
        if primary_provider and primary_provider not in exclude:
            registration = self._providers.get(primary_provider)
            if registration and registration.is_available and registration.supports(capability):
                chain.append(primary_provider)
                exclude.add(primary_provider)

        # Get remaining providers sorted by priority
        providers = self.get_providers_for_capability(
            capability,
            exclude_providers=list(exclude),
            only_available=True,
        )

        # If prefer_same_quality and we have a primary, prioritize same tier
        if prefer_same_quality and chain:
            primary_reg = self._providers.get(chain[0])
            if primary_reg:
                primary_cap = primary_reg.get_capability(capability)
                if primary_cap:
                    primary_tier = primary_cap.quality_tier
                    # Sort: same tier first, then others
                    def sort_key(reg: ProviderRegistration) -> tuple[int, int]:
                        cap = reg.get_capability(capability)
                        if cap and cap.quality_tier == primary_tier:
                            return (0, cap.priority)
                        return (1, cap.priority if cap else 999)

                    providers.sort(key=sort_key)

        # Add fallbacks up to limit
        for reg in providers:
            if len(chain) >= max_fallbacks + 1:  # +1 for primary
                break
            if reg.provider_name not in exclude:
                chain.append(reg.provider_name)

        return chain

    def create_adapter(
        self,
        provider_name: str,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> ProviderAdapter:
        """Create an adapter instance for a provider.

        Args:
            provider_name: Name of the provider
            api_key: API key for the provider
            model_name: Optional model name override
            **kwargs: Additional configuration for the adapter

        Returns:
            Configured ProviderAdapter instance

        Raises:
            ValueError: If provider not found or no factory registered
        """
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not registered")

        if provider_name not in self._adapter_factories:
            raise ValueError(f"No adapter factory registered for '{provider_name}'")

        factory = self._adapter_factories[provider_name]
        return factory(api_key=api_key, model_name=model_name, **kwargs)

    def get_all_providers(self) -> list[ProviderRegistration]:
        """Get all registered providers.

        Returns:
            List of all provider registrations
        """
        return list(self._providers.values())

    def get_all_capabilities(self) -> list[Capability]:
        """Get all capabilities with at least one provider.

        Returns:
            List of capabilities that have registered providers
        """
        return [cap for cap, providers in self._capability_index.items() if providers]

    def is_capability_available(self, capability: Capability) -> bool:
        """Check if any provider offers a capability.

        Args:
            capability: The capability to check

        Returns:
            True if at least one available provider supports it
        """
        providers = self.get_providers_for_capability(capability, only_available=True)
        return len(providers) > 0

    def estimate_cost(
        self,
        capability: Capability,
        provider_name: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_seconds: float = 0,
        character_count: int = 0,
        request_count: int = 1,
    ) -> float | None:
        """Estimate cost for an operation.

        Args:
            capability: The capability to use
            provider_name: The provider to use
            input_tokens: Number of input tokens (LLM)
            output_tokens: Number of output tokens (LLM)
            duration_seconds: Audio duration (transcription)
            character_count: Number of characters (PII)
            request_count: Number of requests

        Returns:
            Estimated cost in USD, or None if provider not found
        """
        cap_meta = self.get_capability_metadata(capability, provider_name)
        if not cap_meta:
            return None

        cost = cap_meta.estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_seconds=duration_seconds,
            character_count=character_count,
            request_count=request_count,
        )
        return float(cost)

    def mark_provider_unavailable(self, provider_name: str) -> None:
        """Mark a provider as temporarily unavailable.

        Use this when a provider is experiencing issues.
        The provider will be excluded from fallback chains.

        Args:
            provider_name: Name of the provider
        """
        if provider_name in self._providers:
            self._providers[provider_name].is_available = False
            logger.warning(f"Provider marked unavailable: {provider_name}")

    def mark_provider_available(self, provider_name: str) -> None:
        """Mark a provider as available again.

        Args:
            provider_name: Name of the provider
        """
        if provider_name in self._providers:
            self._providers[provider_name].is_available = True
            logger.info(f"Provider marked available: {provider_name}")


# Singleton instance
_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry singleton.

    Returns:
        The singleton CapabilityRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry


def reset_capability_registry() -> None:
    """Reset the capability registry (for testing).

    Warning: Only use in tests!
    """
    global _registry
    _registry = None
