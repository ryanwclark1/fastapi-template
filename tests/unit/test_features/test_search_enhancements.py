"""Tests for search enhancement features.

Tests for:
- Circuit breaker
- Intent classification
- Configuration management
- Ranking adjustments
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.features.search.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)
from example_service.features.search.config import (
    EntitySearchConfig,
    SearchConfiguration,
    SearchEntityRegistry,
    SearchSettings,
    create_default_configuration,
    get_search_config,
)
from example_service.features.search.intent import (
    IntentClassifier,
    IntentType,
    QueryIntent,
    classify_query_intent,
)
from example_service.features.search.ranking import (
    ClickBoostRanker,
    ClickSignal,
    RankingConfig,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_closed(self):
        """Circuit breaker starts in closed state."""
        breaker = CircuitBreaker(threshold=3, timeout=10)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    def test_can_execute_when_closed(self):
        """Requests pass through when closed."""
        breaker = CircuitBreaker(threshold=3, timeout=10)
        assert breaker.can_execute()

    def test_opens_after_threshold_failures(self):
        """Circuit opens after reaching failure threshold."""
        breaker = CircuitBreaker(threshold=3, timeout=10)

        # Record failures up to threshold
        for _ in range(3):
            breaker.can_execute()
            breaker.record_failure()

        assert breaker.is_open
        assert not breaker.can_execute()

    def test_success_resets_failure_count_in_half_open(self):
        """Success in half-open state closes the circuit."""
        breaker = CircuitBreaker(threshold=2, timeout=0)  # 0 timeout for immediate retry

        # Open the circuit
        breaker.can_execute()
        breaker.record_failure()
        breaker.can_execute()
        breaker.record_failure()
        assert breaker.is_open

        # Wait for timeout and try again (immediately due to timeout=0)
        assert breaker.can_execute()  # Should transition to half-open
        assert breaker.is_half_open

        breaker.record_success()
        assert breaker.is_closed

    def test_failure_in_half_open_reopens(self):
        """Failure in half-open state reopens the circuit."""
        breaker = CircuitBreaker(threshold=2, timeout=0)

        # Open the circuit
        breaker.can_execute()
        breaker.record_failure()
        breaker.can_execute()
        breaker.record_failure()

        # Transition to half-open
        assert breaker.can_execute()
        assert breaker.is_half_open

        # Fail again
        breaker.record_failure()
        assert breaker.is_open

    def test_reset(self):
        """Manual reset closes the circuit."""
        breaker = CircuitBreaker(threshold=2, timeout=30)

        # Open the circuit
        breaker.can_execute()
        breaker.record_failure()
        breaker.can_execute()
        breaker.record_failure()
        assert breaker.is_open

        # Reset
        breaker.reset()
        assert breaker.is_closed
        assert breaker.can_execute()

    def test_get_stats(self):
        """Stats are tracked correctly."""
        breaker = CircuitBreaker(threshold=5, timeout=30, name="test")

        breaker.can_execute()
        breaker.record_success()
        breaker.can_execute()
        breaker.record_failure()

        stats = breaker.get_stats()
        assert stats.state == CircuitState.CLOSED
        assert stats.success_count == 1
        assert stats.failure_count == 1
        assert stats.total_requests == 2


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""

    def test_get_or_create(self):
        """Creates and returns circuit breakers."""
        registry = CircuitBreakerRegistry()

        breaker1 = registry.get_or_create("cache", threshold=5)
        breaker2 = registry.get_or_create("cache", threshold=10)  # Different threshold

        # Should return the same instance
        assert breaker1 is breaker2
        assert breaker1.threshold == 5  # Original threshold

    def test_get_all_stats(self):
        """Returns stats for all breakers."""
        registry = CircuitBreakerRegistry()

        registry.get_or_create("cache")
        registry.get_or_create("database")

        stats = registry.get_all_stats()
        assert "cache" in stats
        assert "database" in stats


class TestIntentClassifier:
    """Tests for IntentClassifier."""

    def test_informational_question(self):
        """Classifies questions as informational."""
        classifier = IntentClassifier()

        intent = classifier.classify("how to configure python logging")
        assert intent.type == IntentType.INFORMATIONAL
        assert "question_word" in intent.signals

    def test_navigational_single_term(self):
        """Classifies single terms as navigational."""
        classifier = IntentClassifier()

        intent = classifier.classify("settings")
        assert intent.type == IntentType.NAVIGATIONAL

    def test_transactional_action(self):
        """Classifies action queries as transactional."""
        classifier = IntentClassifier()

        intent = classifier.classify("create new user account")
        assert intent.type == IntentType.TRANSACTIONAL
        assert "action_verb" in intent.signals

    def test_exploratory_browse(self):
        """Classifies browse queries as exploratory."""
        classifier = IntentClassifier()

        intent = classifier.classify("browse all categories")
        assert intent.type == IntentType.EXPLORATORY

    def test_empty_query(self):
        """Handles empty queries gracefully."""
        classifier = IntentClassifier()

        intent = classifier.classify("")
        assert intent.type == IntentType.UNKNOWN
        assert intent.confidence == 0.0

    def test_suggested_adjustments(self):
        """Returns suggested adjustments for intents."""
        classifier = IntentClassifier()

        intent = classifier.classify("how to use python")
        assert "expand_synonyms" in intent.suggested_adjustments

        intent = classifier.classify("settings page")
        assert intent.suggested_adjustments.get("prefer_exact_match") is True

    def test_classify_query_intent_convenience(self):
        """Convenience function works correctly."""
        intent = classify_query_intent("what is python")
        assert intent.type == IntentType.INFORMATIONAL


class TestSearchConfiguration:
    """Tests for SearchConfiguration."""

    def test_default_configuration(self):
        """Default configuration has expected values."""
        config = create_default_configuration()

        assert config.settings.enable_synonyms is True
        assert config.settings.enable_click_boosting is True
        assert len(config.entity_registry.list_entities()) > 0

    def test_entity_registry(self):
        """Entity registry manages entities correctly."""
        registry = SearchEntityRegistry()

        config = EntitySearchConfig(
            display_name="Test",
            model_path="test.models.Test",
            search_fields=["name", "description"],
        )

        registry.register("test", config)
        assert registry.get("test") == config
        assert "test" in registry.list_entities()

        registry.unregister("test")
        assert registry.get("test") is None

    def test_get_enabled_features(self):
        """Enabled features are listed correctly."""
        config = create_default_configuration()
        features = config.get_enabled_features()

        assert "full_text_search" in features
        assert "synonyms" in features
        assert "click_boosting" in features


class TestSearchSettings:
    """Tests for SearchSettings."""

    def test_default_values(self):
        """Default settings have expected values."""
        settings = SearchSettings()

        assert settings.enable_synonyms is True
        assert settings.cache_ttl_seconds == 300
        assert settings.slow_query_threshold_ms == 500

    def test_custom_values(self):
        """Custom values are applied."""
        settings = SearchSettings(
            enable_synonyms=False,
            cache_ttl_seconds=600,
            slow_query_threshold_ms=1000,
        )

        assert settings.enable_synonyms is False
        assert settings.cache_ttl_seconds == 600
        assert settings.slow_query_threshold_ms == 1000


class TestRankingConfig:
    """Tests for RankingConfig."""

    def test_default_config(self):
        """Default ranking config has expected values."""
        config = RankingConfig()

        assert config.enable_click_boost is True
        assert config.click_boost_weight == 0.2
        assert config.min_clicks_for_boost == 3

    def test_calculate_final_rank_no_boost(self):
        """Calculates rank without click boost."""
        config = RankingConfig(enable_click_boost=False)
        ranker = ClickBoostRanker.__new__(ClickBoostRanker)
        ranker.config = config

        rank = ranker.calculate_final_rank(0.5, "posts", click_boost=0.3)
        assert rank == 0.5  # No boost applied

    def test_calculate_final_rank_with_boost(self):
        """Calculates rank with click boost."""
        config = RankingConfig(
            enable_click_boost=True,
            click_boost_weight=0.2,
        )
        ranker = ClickBoostRanker.__new__(ClickBoostRanker)
        ranker.config = config

        rank = ranker.calculate_final_rank(0.5, "posts", click_boost=0.5)
        expected = 0.5 * (1 + 0.5 * 0.2)  # 0.55
        assert abs(rank - expected) < 0.001

    def test_calculate_final_rank_with_entity_boost(self):
        """Applies entity-specific boost."""
        config = RankingConfig(
            enable_click_boost=False,
            entity_boosts={"posts": 1.5, "users": 0.8},
        )
        ranker = ClickBoostRanker.__new__(ClickBoostRanker)
        ranker.config = config

        rank = ranker.calculate_final_rank(0.5, "posts")
        assert abs(rank - 0.75) < 0.001


class TestClickSignal:
    """Tests for ClickSignal."""

    def test_click_boost_calculation(self):
        """Click boost is calculated correctly."""
        signal = ClickSignal(
            entity_type="posts",
            entity_id="123",
            total_clicks=10,
            unique_searches=5,
            avg_click_position=2.0,
            last_clicked=datetime.now(UTC),
            ctr=0.3,
        )

        boost = signal.click_boost
        assert 0.0 <= boost <= 1.0
        assert boost > 0  # Has clicks, should have positive boost

    def test_no_clicks_no_boost(self):
        """No clicks means no boost."""
        signal = ClickSignal(
            entity_type="posts",
            entity_id="123",
            total_clicks=0,
            unique_searches=0,
            avg_click_position=0,
            last_clicked=None,
            ctr=0.0,
        )

        assert signal.click_boost == 0.0
