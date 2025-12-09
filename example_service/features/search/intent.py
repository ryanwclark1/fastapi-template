"""Query intent classification for search.

Classifies search queries into intent categories to optimize
result ranking and presentation:
- Navigational: User looking for specific content
- Informational: User seeking information/learning
- Transactional: User wants to take action

Usage:
    classifier = IntentClassifier()
    intent = classifier.classify("how to configure python logging")
    # Returns: QueryIntent(type=INFORMATIONAL, confidence=0.85)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any


class IntentType(StrEnum):
    """Types of search intent."""

    NAVIGATIONAL = "navigational"  # Looking for specific item
    INFORMATIONAL = "informational"  # Seeking information
    TRANSACTIONAL = "transactional"  # Want to take action
    EXPLORATORY = "exploratory"  # Browsing/exploring
    UNKNOWN = "unknown"


@dataclass
class QueryIntent:
    """Classified intent for a search query."""

    type: IntentType
    confidence: float  # 0.0 - 1.0
    signals: list[str] = field(default_factory=list)
    suggested_adjustments: dict[str, Any] = field(default_factory=dict)

    @property
    def is_high_confidence(self) -> bool:
        """Check if classification has high confidence."""
        return self.confidence >= 0.7


@dataclass
class IntentPattern:
    """Pattern for detecting query intent."""

    pattern: re.Pattern[str]
    intent: IntentType
    weight: float = 1.0
    signal: str = ""


class IntentClassifier:
    """Classifies search query intent.

    Uses pattern matching and heuristics to determine user intent,
    which can be used to adjust ranking and result presentation.

    Example:
        classifier = IntentClassifier()

        # Informational query
        intent = classifier.classify("how to implement authentication")
        # intent.type == INFORMATIONAL

        # Navigational query
        intent = classifier.classify("user settings page")
        # intent.type == NAVIGATIONAL
    """

    # Patterns for intent detection
    INFORMATIONAL_PATTERNS: list[IntentPattern] = [
        IntentPattern(
            re.compile(r"^(how|what|why|when|where|which|who)\b", re.I),
            IntentType.INFORMATIONAL,
            weight=1.5,
            signal="question_word",
        ),
        IntentPattern(
            re.compile(r"\b(tutorial|guide|learn|example|explain|documentation|docs)\b", re.I),
            IntentType.INFORMATIONAL,
            weight=1.3,
            signal="learning_term",
        ),
        IntentPattern(
            re.compile(r"\b(difference between|vs|versus|compare|comparison)\b", re.I),
            IntentType.INFORMATIONAL,
            weight=1.2,
            signal="comparison",
        ),
        IntentPattern(
            re.compile(r"\b(best practices?|recommended|tips?)\b", re.I),
            IntentType.INFORMATIONAL,
            weight=1.1,
            signal="advice_seeking",
        ),
        IntentPattern(
            re.compile(r"\?$"),
            IntentType.INFORMATIONAL,
            weight=0.8,
            signal="question_mark",
        ),
    ]

    NAVIGATIONAL_PATTERNS: list[IntentPattern] = [
        IntentPattern(
            re.compile(r"^(go to|open|find|show|view)\b", re.I),
            IntentType.NAVIGATIONAL,
            weight=1.5,
            signal="navigation_command",
        ),
        IntentPattern(
            re.compile(r"\b(page|section|menu|settings?|dashboard|profile)\b", re.I),
            IntentType.NAVIGATIONAL,
            weight=1.2,
            signal="ui_element",
        ),
        IntentPattern(
            re.compile(r"^[a-zA-Z0-9_-]+$"),  # Single word/identifier
            IntentType.NAVIGATIONAL,
            weight=0.6,
            signal="single_term",
        ),
        IntentPattern(
            re.compile(r"\b(specific|exact|named?)\b", re.I),
            IntentType.NAVIGATIONAL,
            weight=1.0,
            signal="specificity",
        ),
    ]

    TRANSACTIONAL_PATTERNS: list[IntentPattern] = [
        IntentPattern(
            re.compile(r"^(create|add|new|make|delete|remove|update|edit|change)\b", re.I),
            IntentType.TRANSACTIONAL,
            weight=1.5,
            signal="action_verb",
        ),
        IntentPattern(
            re.compile(r"\b(submit|save|send|post|upload|download)\b", re.I),
            IntentType.TRANSACTIONAL,
            weight=1.3,
            signal="transaction_verb",
        ),
        IntentPattern(
            re.compile(r"\b(configure|setup|install|enable|disable)\b", re.I),
            IntentType.TRANSACTIONAL,
            weight=1.2,
            signal="configuration",
        ),
    ]

    EXPLORATORY_PATTERNS: list[IntentPattern] = [
        IntentPattern(
            re.compile(r"^(browse|explore|list|all|show all)\b", re.I),
            IntentType.EXPLORATORY,
            weight=1.4,
            signal="exploration_command",
        ),
        IntentPattern(
            re.compile(r"\b(related|similar|like|more)\b", re.I),
            IntentType.EXPLORATORY,
            weight=1.0,
            signal="related_content",
        ),
        IntentPattern(
            re.compile(r"\b(options?|choices?|alternatives?)\b", re.I),
            IntentType.EXPLORATORY,
            weight=1.1,
            signal="options_seeking",
        ),
    ]

    def __init__(
        self,
        custom_patterns: list[IntentPattern] | None = None,
        default_intent: IntentType = IntentType.INFORMATIONAL,
        min_confidence: float = 0.3,
    ) -> None:
        """Initialize the classifier.

        Args:
            custom_patterns: Additional patterns to use.
            default_intent: Intent to return when uncertain.
            min_confidence: Minimum confidence threshold.
        """
        self.default_intent = default_intent
        self.min_confidence = min_confidence

        # Combine all patterns
        self.patterns: dict[IntentType, list[IntentPattern]] = {
            IntentType.INFORMATIONAL: list(self.INFORMATIONAL_PATTERNS),
            IntentType.NAVIGATIONAL: list(self.NAVIGATIONAL_PATTERNS),
            IntentType.TRANSACTIONAL: list(self.TRANSACTIONAL_PATTERNS),
            IntentType.EXPLORATORY: list(self.EXPLORATORY_PATTERNS),
        }

        # Add custom patterns
        if custom_patterns:
            for pattern in custom_patterns:
                if pattern.intent not in self.patterns:
                    self.patterns[pattern.intent] = []
                self.patterns[pattern.intent].append(pattern)

    def classify(self, query: str) -> QueryIntent:
        """Classify a search query's intent.

        Args:
            query: The search query.

        Returns:
            QueryIntent with classification.
        """
        if not query or not query.strip():
            return QueryIntent(
                type=IntentType.UNKNOWN,
                confidence=0.0,
            )

        query = query.strip()
        scores: dict[IntentType, float] = {
            IntentType.INFORMATIONAL: 0.0,
            IntentType.NAVIGATIONAL: 0.0,
            IntentType.TRANSACTIONAL: 0.0,
            IntentType.EXPLORATORY: 0.0,
        }
        signals: dict[IntentType, list[str]] = {t: [] for t in scores}

        # Check patterns for each intent type
        for intent_type, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern.pattern.search(query):
                    scores[intent_type] += pattern.weight
                    if pattern.signal:
                        signals[intent_type].append(pattern.signal)

        # Apply query length heuristics
        word_count = len(query.split())
        if word_count <= 2:
            # Short queries are often navigational
            scores[IntentType.NAVIGATIONAL] += 0.3
        elif word_count >= 5:
            # Longer queries are often informational
            scores[IntentType.INFORMATIONAL] += 0.3

        # Find the highest scoring intent
        max_score = max(scores.values())
        if max_score < self.min_confidence:
            return QueryIntent(
                type=self.default_intent,
                confidence=self.min_confidence,
                signals=["default_fallback"],
                suggested_adjustments=self._get_adjustments(self.default_intent),
            )

        # Normalize scores to confidence
        total_score = sum(scores.values())
        best_intent = max(scores, key=scores.get)  # type: ignore
        confidence = scores[best_intent] / total_score if total_score > 0 else 0.0

        return QueryIntent(
            type=best_intent,
            confidence=min(confidence, 1.0),
            signals=signals[best_intent],
            suggested_adjustments=self._get_adjustments(best_intent),
        )

    def _get_adjustments(self, intent: IntentType) -> dict[str, Any]:
        """Get suggested ranking adjustments for an intent.

        Args:
            intent: The classified intent.

        Returns:
            Dictionary of suggested adjustments.
        """
        adjustments: dict[IntentType, dict[str, Any]] = {
            IntentType.NAVIGATIONAL: {
                "prefer_exact_match": True,
                "boost_title_matches": 1.5,
                "limit_results": 5,
                "skip_fuzzy": True,
            },
            IntentType.INFORMATIONAL: {
                "prefer_exact_match": False,
                "boost_content_matches": 1.2,
                "include_related": True,
                "expand_synonyms": True,
            },
            IntentType.TRANSACTIONAL: {
                "prefer_exact_match": True,
                "boost_recent": 1.3,
                "filter_active_only": True,
            },
            IntentType.EXPLORATORY: {
                "prefer_exact_match": False,
                "include_facets": True,
                "increase_limit": True,
                "show_categories": True,
            },
            IntentType.UNKNOWN: {
                "use_defaults": True,
            },
        }

        return adjustments.get(intent, {})

    def get_intent_summary(self, query: str) -> dict[str, Any]:
        """Get a detailed intent summary for a query.

        Args:
            query: The search query.

        Returns:
            Dictionary with intent analysis.
        """
        intent = self.classify(query)

        return {
            "query": query,
            "intent": intent.type.value,
            "confidence": round(intent.confidence, 3),
            "is_high_confidence": intent.is_high_confidence,
            "signals": intent.signals,
            "adjustments": intent.suggested_adjustments,
        }


# Convenience function
def classify_query_intent(query: str) -> QueryIntent:
    """Classify a search query's intent.

    Args:
        query: The search query.

    Returns:
        QueryIntent with classification.
    """
    classifier = IntentClassifier()
    return classifier.classify(query)


__all__ = [
    "IntentClassifier",
    "IntentPattern",
    "IntentType",
    "QueryIntent",
    "classify_query_intent",
]
