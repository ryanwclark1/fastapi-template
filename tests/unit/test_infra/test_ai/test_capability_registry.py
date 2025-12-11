"""Unit tests for Capability Registry.

Tests cover:
- Provider registration and unregistration
- Capability discovery and filtering
- Fallback chain building
- Cost estimation
- Provider availability management
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from example_service.infra.ai.capabilities.registry import (
    CapabilityRegistry,
    get_capability_registry,
    reset_capability_registry,
)
from example_service.infra.ai.capabilities.types import (
    Capability,
    CapabilityMetadata,
    CostUnit,
    ProviderRegistration,
    ProviderType,
    QualityTier,
)

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    """Create a fresh registry for each test."""
    return CapabilityRegistry()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset global registry before/after each test."""
    reset_capability_registry()
    yield
    reset_capability_registry()


@pytest.fixture
def deepgram_registration():
    """Create a Deepgram provider registration."""
    return ProviderRegistration(
        provider_name="deepgram",
        provider_type=ProviderType.EXTERNAL,
        requires_api_key=True,
        capabilities=[
            CapabilityMetadata(
                capability=Capability.TRANSCRIPTION,
                provider_name="deepgram",
                quality_tier=QualityTier.PREMIUM,
                cost_per_unit=Decimal("0.0043"),
                cost_unit=CostUnit.PER_MINUTE,
                priority=1,
            ),
            CapabilityMetadata(
                capability=Capability.TRANSCRIPTION_DIARIZATION,
                provider_name="deepgram",
                quality_tier=QualityTier.PREMIUM,
                cost_per_unit=Decimal("0.0063"),
                cost_unit=CostUnit.PER_MINUTE,
                priority=1,
            ),
        ],
    )


@pytest.fixture
def openai_registration():
    """Create an OpenAI provider registration."""
    return ProviderRegistration(
        provider_name="openai",
        provider_type=ProviderType.EXTERNAL,
        requires_api_key=True,
        capabilities=[
            CapabilityMetadata(
                capability=Capability.TRANSCRIPTION,
                provider_name="openai",
                quality_tier=QualityTier.STANDARD,
                cost_per_unit=Decimal("0.006"),
                cost_unit=CostUnit.PER_MINUTE,
                priority=2,  # Lower priority than Deepgram
            ),
            CapabilityMetadata(
                capability=Capability.LLM_GENERATION,
                provider_name="openai",
                quality_tier=QualityTier.PREMIUM,
                cost_per_unit=Decimal("0.015"),
                cost_unit=CostUnit.PER_1K_TOKENS,
                priority=1,
            ),
        ],
    )


@pytest.fixture
def anthropic_registration():
    """Create an Anthropic provider registration."""
    return ProviderRegistration(
        provider_name="anthropic",
        provider_type=ProviderType.EXTERNAL,
        requires_api_key=True,
        capabilities=[
            CapabilityMetadata(
                capability=Capability.LLM_GENERATION,
                provider_name="anthropic",
                quality_tier=QualityTier.PREMIUM,
                cost_per_unit=Decimal("0.015"),
                cost_unit=CostUnit.PER_1K_TOKENS,
                priority=2,  # Same tier but lower priority
            ),
        ],
    )


@pytest.fixture
def accent_registration():
    """Create an internal Accent provider registration."""
    return ProviderRegistration(
        provider_name="accent_redaction",
        provider_type=ProviderType.INTERNAL,
        requires_api_key=False,  # Internal service
        capabilities=[
            CapabilityMetadata(
                capability=Capability.PII_REDACTION,
                provider_name="accent_redaction",
                quality_tier=QualityTier.PREMIUM,
                cost_per_unit=Decimal("0.001"),
                cost_unit=CostUnit.PER_CHARACTER,
                priority=1,
            ),
        ],
    )


# ──────────────────────────────────────────────────────────────
# Test Provider Registration
# ──────────────────────────────────────────────────────────────


class TestProviderRegistration:
    """Tests for provider registration functionality."""

    def test_register_provider_adds_to_registry(self, registry, deepgram_registration):
        """Registering a provider should add it to the registry."""
        registry.register_provider(deepgram_registration)

        assert "deepgram" in registry._providers
        assert registry.get_provider("deepgram") is deepgram_registration

    def test_register_provider_updates_capability_index(
        self, registry, deepgram_registration,
    ):
        """Registering a provider should update the capability index."""
        registry.register_provider(deepgram_registration)

        assert "deepgram" in registry._capability_index[Capability.TRANSCRIPTION]
        assert "deepgram" in registry._capability_index[Capability.TRANSCRIPTION_DIARIZATION]

    def test_register_provider_with_factory(self, registry, deepgram_registration):
        """Registering with a factory should store the factory."""
        mock_factory = MagicMock()
        registry.register_provider(deepgram_registration, adapter_factory=mock_factory)

        assert registry._adapter_factories["deepgram"] is mock_factory

    def test_register_duplicate_updates_existing(self, registry, deepgram_registration):
        """Re-registering a provider should update the existing registration."""
        registry.register_provider(deepgram_registration)

        # Create updated registration
        updated = ProviderRegistration(
            provider_name="deepgram",
            provider_type=ProviderType.EXTERNAL,
            requires_api_key=True,
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION,
                    provider_name="deepgram",
                    quality_tier=QualityTier.PREMIUM,
                    cost_per_unit=Decimal("0.005"),  # Updated cost
                    cost_unit=CostUnit.PER_MINUTE,
                    priority=1,
                ),
            ],
        )
        registry.register_provider(updated)

        reg = registry.get_provider("deepgram")
        cap = reg.get_capability(Capability.TRANSCRIPTION)
        assert cap.cost_per_unit == Decimal("0.005")

    def test_unregister_provider_removes_from_registry(
        self, registry, deepgram_registration,
    ):
        """Unregistering should remove provider from all indexes."""
        registry.register_provider(deepgram_registration)

        result = registry.unregister_provider("deepgram")

        assert result is True
        assert registry.get_provider("deepgram") is None
        assert "deepgram" not in registry._capability_index.get(
            Capability.TRANSCRIPTION, [],
        )

    def test_unregister_nonexistent_returns_false(self, registry):
        """Unregistering non-existent provider should return False."""
        result = registry.unregister_provider("nonexistent")
        assert result is False


# ──────────────────────────────────────────────────────────────
# Test Capability Discovery
# ──────────────────────────────────────────────────────────────


class TestCapabilityDiscovery:
    """Tests for capability discovery functionality."""

    def test_get_providers_returns_sorted_by_priority(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Providers should be returned sorted by priority (lower first)."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)

        assert len(providers) == 2
        assert providers[0].provider_name == "deepgram"  # Priority 1
        assert providers[1].provider_name == "openai"  # Priority 2

    def test_get_providers_filters_by_quality_tier(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should filter providers by quality tier."""
        registry.register_provider(deepgram_registration)  # PREMIUM
        registry.register_provider(openai_registration)  # STANDARD

        premium = registry.get_providers_for_capability(
            Capability.TRANSCRIPTION,
            quality_tier=QualityTier.PREMIUM,
        )
        standard = registry.get_providers_for_capability(
            Capability.TRANSCRIPTION,
            quality_tier=QualityTier.STANDARD,
        )

        assert len(premium) == 1
        assert premium[0].provider_name == "deepgram"
        assert len(standard) == 1
        assert standard[0].provider_name == "openai"

    def test_get_providers_excludes_specified(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should exclude providers in the exclude list."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        providers = registry.get_providers_for_capability(
            Capability.TRANSCRIPTION,
            exclude_providers=["deepgram"],
        )

        assert len(providers) == 1
        assert providers[0].provider_name == "openai"

    def test_get_providers_excludes_unavailable(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should exclude unavailable providers by default."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)
        registry.mark_provider_unavailable("deepgram")

        providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)

        assert len(providers) == 1
        assert providers[0].provider_name == "openai"

    def test_get_providers_includes_unavailable_when_requested(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should include unavailable providers when only_available=False."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)
        registry.mark_provider_unavailable("deepgram")

        providers = registry.get_providers_for_capability(
            Capability.TRANSCRIPTION,
            only_available=False,
        )

        assert len(providers) == 2

    def test_get_providers_returns_empty_for_unknown_capability(self, registry):
        """Should return empty list for capability with no providers."""
        providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)
        assert providers == []


# ──────────────────────────────────────────────────────────────
# Test Cheapest Provider Discovery
# ──────────────────────────────────────────────────────────────


class TestCheapestProvider:
    """Tests for cheapest provider discovery."""

    def test_get_cheapest_finds_lowest_cost(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should find the cheapest provider for a capability."""
        registry.register_provider(deepgram_registration)  # 0.0043/min
        registry.register_provider(openai_registration)  # 0.006/min

        cheapest = registry.get_cheapest_provider(Capability.TRANSCRIPTION)

        assert cheapest == "deepgram"

    def test_get_cheapest_respects_quality_filter(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should respect minimum quality tier when finding cheapest."""
        registry.register_provider(deepgram_registration)  # PREMIUM
        registry.register_provider(openai_registration)  # STANDARD (cheaper but lower tier)

        # When requiring PREMIUM, should only consider deepgram
        cheapest = registry.get_cheapest_provider(
            Capability.TRANSCRIPTION,
            min_quality_tier=QualityTier.PREMIUM,
        )

        assert cheapest == "deepgram"

    def test_get_cheapest_excludes_providers(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should respect exclude list when finding cheapest."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        cheapest = registry.get_cheapest_provider(
            Capability.TRANSCRIPTION,
            exclude_providers=["deepgram"],
        )

        assert cheapest == "openai"

    def test_get_cheapest_returns_none_when_no_providers(self, registry):
        """Should return None when no providers match."""
        cheapest = registry.get_cheapest_provider(Capability.TRANSCRIPTION)
        assert cheapest is None


# ──────────────────────────────────────────────────────────────
# Test Fallback Chain Building
# ──────────────────────────────────────────────────────────────


class TestFallbackChain:
    """Tests for fallback chain building."""

    def test_build_chain_starts_with_primary(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Chain should start with specified primary provider."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        chain = registry.build_fallback_chain(
            Capability.TRANSCRIPTION,
            primary_provider="openai",  # Choose lower priority as primary
        )

        assert chain[0] == "openai"
        assert "deepgram" in chain

    def test_build_chain_uses_priority_without_primary(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Without primary, chain should follow priority order."""
        registry.register_provider(deepgram_registration)  # Priority 1
        registry.register_provider(openai_registration)  # Priority 2

        chain = registry.build_fallback_chain(Capability.TRANSCRIPTION)

        assert chain == ["deepgram", "openai"]

    def test_build_chain_respects_max_fallbacks(
        self,
        registry,
        deepgram_registration,
        openai_registration,
        anthropic_registration,
    ):
        """Chain should respect max_fallbacks limit."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)
        registry.register_provider(anthropic_registration)

        chain = registry.build_fallback_chain(
            Capability.LLM_GENERATION,
            max_fallbacks=1,
        )

        # 1 primary + 1 fallback = 2 max
        assert len(chain) <= 2

    def test_build_chain_excludes_providers(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Chain should respect exclude list."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        chain = registry.build_fallback_chain(
            Capability.TRANSCRIPTION,
            exclude_providers=["deepgram"],
        )

        assert "deepgram" not in chain
        assert chain == ["openai"]

    def test_build_chain_skips_unavailable_primary(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Chain should skip unavailable primary provider."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)
        registry.mark_provider_unavailable("deepgram")

        chain = registry.build_fallback_chain(
            Capability.TRANSCRIPTION,
            primary_provider="deepgram",  # Unavailable
        )

        assert "deepgram" not in chain
        assert chain == ["openai"]


# ──────────────────────────────────────────────────────────────
# Test Adapter Creation
# ──────────────────────────────────────────────────────────────


class TestAdapterCreation:
    """Tests for adapter factory functionality."""

    def test_create_adapter_calls_factory(self, registry, deepgram_registration):
        """Create adapter should call the registered factory."""
        mock_factory = MagicMock()
        mock_adapter = MagicMock()
        mock_factory.return_value = mock_adapter

        registry.register_provider(deepgram_registration, adapter_factory=mock_factory)

        adapter = registry.create_adapter("deepgram", api_key="test-key")

        mock_factory.assert_called_once_with(api_key="test-key", model_name=None)
        assert adapter is mock_adapter

    def test_create_adapter_raises_for_unknown_provider(self, registry):
        """Should raise ValueError for unknown provider."""
        with pytest.raises(ValueError, match="not registered"):
            registry.create_adapter("unknown")

    def test_create_adapter_raises_without_factory(
        self, registry, deepgram_registration,
    ):
        """Should raise ValueError when no factory registered."""
        registry.register_provider(deepgram_registration)  # No factory

        with pytest.raises(ValueError, match="No adapter factory"):
            registry.create_adapter("deepgram")


# ──────────────────────────────────────────────────────────────
# Test Cost Estimation
# ──────────────────────────────────────────────────────────────


class TestCostEstimation:
    """Tests for cost estimation functionality."""

    def test_estimate_cost_for_transcription(self, registry, deepgram_registration):
        """Should estimate transcription cost based on duration."""
        registry.register_provider(deepgram_registration)

        cost = registry.estimate_cost(
            Capability.TRANSCRIPTION,
            provider_name="deepgram",
            duration_seconds=600,  # 10 minutes
        )

        # 10 minutes * $0.0043/minute = $0.043
        assert cost == pytest.approx(0.043, rel=0.01)

    def test_estimate_cost_for_llm(self, registry, openai_registration):
        """Should estimate LLM cost based on tokens."""
        registry.register_provider(openai_registration)

        cost = registry.estimate_cost(
            Capability.LLM_GENERATION,
            provider_name="openai",
            input_tokens=1000,
        )

        # 1000 tokens * $0.015 per 1K = $0.015
        assert cost == pytest.approx(0.015, rel=0.01)

    def test_estimate_cost_returns_none_for_unknown(self, registry):
        """Should return None for unknown provider."""
        cost = registry.estimate_cost(
            Capability.TRANSCRIPTION,
            provider_name="unknown",
            duration_seconds=60,
        )

        assert cost is None


# ──────────────────────────────────────────────────────────────
# Test Provider Availability
# ──────────────────────────────────────────────────────────────


class TestProviderAvailability:
    """Tests for provider availability management."""

    def test_mark_unavailable_sets_flag(self, registry, deepgram_registration):
        """Marking unavailable should set is_available to False."""
        registry.register_provider(deepgram_registration)
        assert registry.get_provider("deepgram").is_available is True

        registry.mark_provider_unavailable("deepgram")

        assert registry.get_provider("deepgram").is_available is False

    def test_mark_available_sets_flag(self, registry, deepgram_registration):
        """Marking available should set is_available to True."""
        registry.register_provider(deepgram_registration)
        registry.mark_provider_unavailable("deepgram")

        registry.mark_provider_available("deepgram")

        assert registry.get_provider("deepgram").is_available is True

    def test_is_capability_available_true_when_provider_exists(
        self, registry, deepgram_registration,
    ):
        """Should return True when available provider exists."""
        registry.register_provider(deepgram_registration)

        assert registry.is_capability_available(Capability.TRANSCRIPTION) is True

    def test_is_capability_available_false_when_all_unavailable(
        self, registry, deepgram_registration,
    ):
        """Should return False when all providers unavailable."""
        registry.register_provider(deepgram_registration)
        registry.mark_provider_unavailable("deepgram")

        assert registry.is_capability_available(Capability.TRANSCRIPTION) is False


# ──────────────────────────────────────────────────────────────
# Test Singleton Behavior
# ──────────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for singleton registry behavior."""

    def test_get_registry_returns_same_instance(self):
        """get_capability_registry should return same instance."""
        registry1 = get_capability_registry()
        registry2 = get_capability_registry()

        assert registry1 is registry2

    def test_reset_creates_new_instance(self):
        """reset_capability_registry should create fresh instance."""
        registry1 = get_capability_registry()
        reset_capability_registry()
        registry2 = get_capability_registry()

        assert registry1 is not registry2


# ──────────────────────────────────────────────────────────────
# Test Introspection Methods
# ──────────────────────────────────────────────────────────────


class TestIntrospection:
    """Tests for registry introspection methods."""

    def test_get_all_providers(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should return all registered providers."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        providers = registry.get_all_providers()

        assert len(providers) == 2
        names = {p.provider_name for p in providers}
        assert names == {"deepgram", "openai"}

    def test_get_all_capabilities(
        self, registry, deepgram_registration, openai_registration,
    ):
        """Should return all capabilities with providers."""
        registry.register_provider(deepgram_registration)
        registry.register_provider(openai_registration)

        caps = registry.get_all_capabilities()

        assert Capability.TRANSCRIPTION in caps
        assert Capability.TRANSCRIPTION_DIARIZATION in caps
        assert Capability.LLM_GENERATION in caps

    def test_get_capability_metadata(self, registry, deepgram_registration):
        """Should return capability metadata for specific provider."""
        registry.register_provider(deepgram_registration)

        meta = registry.get_capability_metadata(Capability.TRANSCRIPTION, "deepgram")

        assert meta is not None
        assert meta.quality_tier == QualityTier.PREMIUM
        assert meta.cost_per_unit == Decimal("0.0043")

    def test_get_capability_metadata_returns_none_for_missing(self, registry):
        """Should return None for missing provider/capability."""
        meta = registry.get_capability_metadata(Capability.TRANSCRIPTION, "unknown")
        assert meta is None
