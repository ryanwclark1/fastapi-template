"""AI Capabilities Layer.

This module provides the capability discovery and provider routing infrastructure:

- Capability: Enum of AI capabilities (transcription, llm, pii_redaction, etc.)
- CapabilityMetadata: Metadata about a provider's capability (cost, quality, etc.)
- ProviderRegistration: Complete registration of a provider with all capabilities
- CapabilityRegistry: Central hub for provider discovery and selection
- ProviderAdapter: Base protocol for all provider adapters
- OperationResult: Standardized result from any AI operation

Architecture:
    Registry → Adapters → Existing Providers

    The registry manages provider discovery and selection.
    Adapters wrap existing providers (OpenAI, Deepgram, etc.) with:
    - Capability declarations
    - Cost tracking and usage metrics
    - Standardized result format

Example:
    from example_service.infra.ai.capabilities import (
        Capability,
        get_capability_registry,
    )

    registry = get_capability_registry()

    # Find all providers that support transcription
    providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)

    # Get cheapest provider for LLM
    cheapest = registry.get_cheapest_provider(Capability.LLM_GENERATION)

    # Build fallback chain: primary -> fallback1 -> fallback2
    chain = registry.build_fallback_chain(
        Capability.TRANSCRIPTION,
        primary_provider="deepgram",
        max_fallbacks=3,
    )
"""

from example_service.infra.ai.capabilities.builtin_providers import (
    get_provider_info,
    register_builtin_providers,
)
from example_service.infra.ai.capabilities.registry import (
    CapabilityRegistry,
    get_capability_registry,
    reset_capability_registry,
)
from example_service.infra.ai.capabilities.types import (
    Capability,
    CapabilityMetadata,
    CostUnit,
    OperationResult,
    ProviderRegistration,
    ProviderType,
    QualityTier,
)

__all__ = [
    # Types
    "Capability",
    "CapabilityMetadata",
    # Registry
    "CapabilityRegistry",
    "CostUnit",
    "OperationResult",
    "ProviderRegistration",
    "ProviderType",
    "QualityTier",
    "get_capability_registry",
    "get_provider_info",
    # Provider Registration
    "register_builtin_providers",
    "reset_capability_registry",
]
