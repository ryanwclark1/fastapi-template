"""Advanced search query parser for PostgreSQL full-text search.

This module provides a parser for converting user-friendly search queries
into PostgreSQL tsquery expressions. It supports:

Basic syntax:
- word: Match the word (stemmed)
- "exact phrase": Match exact phrase
- -word: Exclude word
- word1 OR word2: Either word
- word1 AND word2: Both words (implicit)

Advanced syntax:
- field:value: Search specific field
- field:"exact phrase": Exact phrase in field
- word*: Prefix matching
- ~word: Fuzzy match (if pg_trgm available)

Operators:
- ( ): Grouping
- !: NOT (alternative to -)
- |: OR (alternative to OR)
- &: AND (alternative to AND)

Range queries (for numeric/date fields):
- field:>value: Greater than
- field:>=value: Greater than or equal
- field:<value: Less than
- field:<=value: Less than or equal
- field:[min TO max]: Range (inclusive)
- field:{min TO max}: Range (exclusive)

Usage:
    from example_service.core.database.search.parser import SearchQueryParser

    parser = SearchQueryParser(config="english")
    result = parser.parse('title:"python tutorial" author:john -draft')

    # Use result.tsquery for the main FTS query
    # Use result.field_filters for field-specific conditions
    # Use result.exclusions for excluded terms
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TYPE_CHECKING

from sqlalchemy import func, and_, or_, not_

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import InstrumentedAttribute


class TokenType(StrEnum):
    """Types of tokens in a search query."""

    WORD = "word"
    PHRASE = "phrase"
    FIELD_TERM = "field_term"
    FIELD_PHRASE = "field_phrase"
    FIELD_PREFIX = "field_prefix"
    FIELD_RANGE = "field_range"
    PREFIX = "prefix"
    FUZZY = "fuzzy"
    EXCLUDE = "exclude"
    OR = "or"
    AND = "and"
    LPAREN = "lparen"
    RPAREN = "rparen"


@dataclass
class Token:
    """A parsed token from the search query."""

    type: TokenType
    value: str
    field: str | None = None
    boost: float | None = None
    range_min: str | None = None
    range_max: str | None = None
    range_inclusive: bool = True


@dataclass
class ParsedQuery:
    """Result of parsing a search query.

    Attributes:
        tsquery_parts: Parts to combine into a tsquery
        field_filters: Field-specific search conditions
        exclusions: Terms to exclude
        prefix_terms: Prefix search terms
        fuzzy_terms: Fuzzy search terms
        original_query: The original query string
        normalized_query: Cleaned query for FTS
    """

    tsquery_parts: list[str] = field(default_factory=list)
    field_filters: dict[str, list[str]] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    prefix_terms: list[str] = field(default_factory=list)
    fuzzy_terms: list[str] = field(default_factory=list)
    range_filters: dict[str, tuple[str | None, str | None, bool]] = field(default_factory=dict)
    original_query: str = ""
    normalized_query: str = ""

    def has_fts_query(self) -> bool:
        """Check if there's a valid FTS query."""
        return bool(self.tsquery_parts or self.normalized_query)

    def has_field_filters(self) -> bool:
        """Check if there are field-specific filters."""
        return bool(self.field_filters)

    def has_exclusions(self) -> bool:
        """Check if there are exclusion terms."""
        return bool(self.exclusions)


class SearchQueryParser:
    """Parser for advanced search query syntax.

    Converts user queries into PostgreSQL tsquery expressions and
    additional filter conditions.

    Example:
        parser = SearchQueryParser()

        # Simple query
        result = parser.parse("python programming")
        # result.normalized_query = "python programming"
        # result.tsquery_parts = ["python", "programming"]

        # Field search
        result = parser.parse('title:python author:"John Doe"')
        # result.field_filters = {"title": ["python"], "author": ["John Doe"]}

        # Exclusions
        result = parser.parse("python -java -javascript")
        # result.normalized_query = "python"
        # result.exclusions = ["java", "javascript"]

        # Prefix search
        result = parser.parse("pytho*")
        # result.prefix_terms = ["pytho"]
    """

    # Regex patterns for tokenization
    PATTERNS = {
        # Field with quoted phrase: field:"value" or field:'value'
        "field_phrase": re.compile(r'(\w+):["\']([^"\']+)["\']'),
        # Field with range: field:[min TO max] or field:{min TO max}
        "field_range": re.compile(r'(\w+):[\[\{](\S+)\s+TO\s+(\S+)[\]\}]', re.IGNORECASE),
        # Field with comparison: field:>value, field:>=value, etc.
        "field_compare": re.compile(r'(\w+):(>=?|<=?)(\S+)'),
        # Field with simple value: field:value
        "field_term": re.compile(r'(\w+):(\S+)'),
        # Quoted phrase: "exact phrase"
        "phrase": re.compile(r'["\']([^"\']+)["\']'),
        # Prefix: word*
        "prefix": re.compile(r'(\w+)\*'),
        # Fuzzy: ~word
        "fuzzy": re.compile(r'~(\w+)'),
        # Exclude: -word or !word
        "exclude": re.compile(r'[-!](\w+)'),
        # OR operator
        "or": re.compile(r'\bOR\b|\|', re.IGNORECASE),
        # AND operator
        "and": re.compile(r'\bAND\b|&', re.IGNORECASE),
        # Parentheses
        "lparen": re.compile(r'\('),
        "rparen": re.compile(r'\)'),
        # Plain word
        "word": re.compile(r'\b(\w+)\b'),
    }

    def __init__(
        self,
        config: str = "english",
        default_operator: str = "AND",
        enable_fuzzy: bool = True,
        enable_prefix: bool = True,
    ) -> None:
        """Initialize the search query parser.

        Args:
            config: PostgreSQL text search configuration
            default_operator: Default operator between terms (AND/OR)
            enable_fuzzy: Enable fuzzy (~) search terms
            enable_prefix: Enable prefix (*) search terms
        """
        self.config = config
        self.default_operator = default_operator.upper()
        self.enable_fuzzy = enable_fuzzy
        self.enable_prefix = enable_prefix

    def parse(self, query: str) -> ParsedQuery:
        """Parse a search query string.

        Args:
            query: User's search query

        Returns:
            ParsedQuery with parsed components
        """
        result = ParsedQuery(original_query=query)

        if not query or not query.strip():
            return result

        query = query.strip()
        tokens = self._tokenize(query)
        self._process_tokens(tokens, result)
        result.normalized_query = self._build_normalized_query(result)

        return result

    def _tokenize(self, query: str) -> list[Token]:
        """Tokenize the query string.

        Args:
            query: Query string to tokenize

        Returns:
            List of tokens
        """
        tokens = []
        remaining = query

        while remaining:
            remaining = remaining.lstrip()
            if not remaining:
                break

            matched = False

            # Try field with range first
            match = self.PATTERNS["field_range"].match(remaining)
            if match:
                field_name, min_val, max_val = match.groups()
                is_inclusive = remaining[len(field_name) + 1] == "["
                tokens.append(Token(
                    type=TokenType.FIELD_RANGE,
                    value=f"{min_val} TO {max_val}",
                    field=field_name,
                    range_min=min_val if min_val != "*" else None,
                    range_max=max_val if max_val != "*" else None,
                    range_inclusive=is_inclusive,
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try field with comparison
            match = self.PATTERNS["field_compare"].match(remaining)
            if match:
                field_name, op, value = match.groups()
                if op.startswith(">"):
                    min_val = value
                    max_val = None
                    inclusive = "=" in op
                else:
                    min_val = None
                    max_val = value
                    inclusive = "=" in op
                tokens.append(Token(
                    type=TokenType.FIELD_RANGE,
                    value=value,
                    field=field_name,
                    range_min=min_val,
                    range_max=max_val,
                    range_inclusive=inclusive,
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try field with phrase
            match = self.PATTERNS["field_phrase"].match(remaining)
            if match:
                tokens.append(Token(
                    type=TokenType.FIELD_PHRASE,
                    value=match.group(2),
                    field=match.group(1),
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try field with term
            match = self.PATTERNS["field_term"].match(remaining)
            if match:
                tokens.append(Token(
                    type=TokenType.FIELD_TERM,
                    value=match.group(2),
                    field=match.group(1),
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try quoted phrase
            match = self.PATTERNS["phrase"].match(remaining)
            if match:
                tokens.append(Token(
                    type=TokenType.PHRASE,
                    value=match.group(1),
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try prefix
            if self.enable_prefix:
                match = self.PATTERNS["prefix"].match(remaining)
                if match:
                    tokens.append(Token(
                        type=TokenType.PREFIX,
                        value=match.group(1),
                    ))
                    remaining = remaining[match.end():]
                    matched = True
                    continue

            # Try fuzzy
            if self.enable_fuzzy:
                match = self.PATTERNS["fuzzy"].match(remaining)
                if match:
                    tokens.append(Token(
                        type=TokenType.FUZZY,
                        value=match.group(1),
                    ))
                    remaining = remaining[match.end():]
                    matched = True
                    continue

            # Try exclude
            match = self.PATTERNS["exclude"].match(remaining)
            if match:
                tokens.append(Token(
                    type=TokenType.EXCLUDE,
                    value=match.group(1),
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try OR
            match = self.PATTERNS["or"].match(remaining)
            if match:
                tokens.append(Token(type=TokenType.OR, value="OR"))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try AND
            match = self.PATTERNS["and"].match(remaining)
            if match:
                tokens.append(Token(type=TokenType.AND, value="AND"))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try parentheses
            match = self.PATTERNS["lparen"].match(remaining)
            if match:
                tokens.append(Token(type=TokenType.LPAREN, value="("))
                remaining = remaining[match.end():]
                matched = True
                continue

            match = self.PATTERNS["rparen"].match(remaining)
            if match:
                tokens.append(Token(type=TokenType.RPAREN, value=")"))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Try plain word
            match = self.PATTERNS["word"].match(remaining)
            if match:
                tokens.append(Token(
                    type=TokenType.WORD,
                    value=match.group(1),
                ))
                remaining = remaining[match.end():]
                matched = True
                continue

            # Skip unrecognized character
            if not matched:
                remaining = remaining[1:]

        return tokens

    def _process_tokens(self, tokens: list[Token], result: ParsedQuery) -> None:
        """Process tokens and populate the ParsedQuery.

        Args:
            tokens: List of tokens
            result: ParsedQuery to populate
        """
        for token in tokens:
            if token.type == TokenType.WORD:
                result.tsquery_parts.append(token.value)

            elif token.type == TokenType.PHRASE:
                # Phrases need special handling for FTS
                result.tsquery_parts.append(f'"{token.value}"')

            elif token.type == TokenType.FIELD_TERM:
                if token.field not in result.field_filters:
                    result.field_filters[token.field] = []
                result.field_filters[token.field].append(token.value)

            elif token.type == TokenType.FIELD_PHRASE:
                if token.field not in result.field_filters:
                    result.field_filters[token.field] = []
                result.field_filters[token.field].append(f'"{token.value}"')

            elif token.type == TokenType.FIELD_RANGE:
                if token.field:
                    result.range_filters[token.field] = (
                        token.range_min,
                        token.range_max,
                        token.range_inclusive,
                    )

            elif token.type == TokenType.PREFIX:
                result.prefix_terms.append(token.value)

            elif token.type == TokenType.FUZZY:
                result.fuzzy_terms.append(token.value)

            elif token.type == TokenType.EXCLUDE:
                result.exclusions.append(token.value)

    def _build_normalized_query(self, result: ParsedQuery) -> str:
        """Build normalized query string for FTS.

        Args:
            result: ParsedQuery with parsed components

        Returns:
            Normalized query string
        """
        parts = []

        for part in result.tsquery_parts:
            parts.append(part)

        # Add prefix terms with wildcard notation
        for prefix in result.prefix_terms:
            parts.append(f"{prefix}:*")

        return " ".join(parts)

    def build_tsquery_sql(
        self,
        parsed: ParsedQuery,
        config: str | None = None,
    ) -> Any:
        """Build SQLAlchemy tsquery expression from parsed query.

        Args:
            parsed: ParsedQuery from parse()
            config: Optional text search config override

        Returns:
            SQLAlchemy expression for tsquery
        """
        config = config or self.config

        if not parsed.has_fts_query():
            # Return a query that matches nothing
            return func.to_tsquery(config, "")

        if parsed.normalized_query:
            # Use websearch for flexibility
            return func.websearch_to_tsquery(config, parsed.normalized_query)

        return func.to_tsquery(config, "")

    def build_exclusion_filter(
        self,
        parsed: ParsedQuery,
        search_column: InstrumentedAttribute[Any],
        config: str | None = None,
    ) -> ColumnElement[bool] | None:
        """Build SQLAlchemy filter for exclusions.

        Args:
            parsed: ParsedQuery from parse()
            search_column: TSVECTOR column
            config: Optional text search config override

        Returns:
            SQLAlchemy NOT condition or None
        """
        config = config or self.config

        if not parsed.exclusions:
            return None

        # Build exclusion tsquery
        exclusion_query = " | ".join(parsed.exclusions)
        ts_query = func.plainto_tsquery(config, exclusion_query)

        return not_(search_column.op("@@")(ts_query))


@dataclass
class QueryRewriter:
    """Rewrites and normalizes search queries.

    Provides query expansion, synonym handling, and normalization.

    Example:
        # With simple dict synonyms
        rewriter = QueryRewriter(
            synonyms={"py": ["python", "python3"]}
        )
        expanded = rewriter.expand_synonyms("py tutorial")
        # Returns: "(py OR python OR python3) tutorial"

        # With SynonymDictionary
        from example_service.core.database.search.synonyms import get_default_synonyms
        rewriter = QueryRewriter.with_dictionary(get_default_synonyms())
    """

    synonyms: dict[str, list[str]] = field(default_factory=dict)
    stop_words: set[str] = field(default_factory=set)
    min_word_length: int = 2
    _synonym_dictionary: Any = field(default=None, repr=False)

    @classmethod
    def with_dictionary(
        cls,
        dictionary: Any,
        stop_words: set[str] | None = None,
        min_word_length: int = 2,
    ) -> "QueryRewriter":
        """Create a QueryRewriter with a SynonymDictionary.

        Args:
            dictionary: SynonymDictionary instance.
            stop_words: Set of stop words to filter.
            min_word_length: Minimum word length to keep.

        Returns:
            QueryRewriter configured with the dictionary.
        """
        rewriter = cls(
            synonyms=dictionary.to_dict() if dictionary else {},
            stop_words=stop_words or set(),
            min_word_length=min_word_length,
        )
        rewriter._synonym_dictionary = dictionary
        return rewriter

    def expand_synonyms(self, query: str) -> str:
        """Expand query terms with synonyms.

        Args:
            query: Original query

        Returns:
            Query with synonym expansions using OR
        """
        # Use SynonymDictionary if available (more sophisticated expansion)
        if self._synonym_dictionary:
            return self._synonym_dictionary.expand_query(query)

        words = query.split()
        expanded = []

        for word in words:
            word_lower = word.lower()
            if word_lower in self.synonyms:
                # Add original and synonyms with OR
                alternatives = [word] + self.synonyms[word_lower]
                expanded.append(f"({' OR '.join(alternatives)})")
            else:
                expanded.append(word)

        return " ".join(expanded)

    def remove_stop_words(self, query: str) -> str:
        """Remove stop words from query.

        Args:
            query: Original query

        Returns:
            Query with stop words removed
        """
        words = query.split()
        filtered = [w for w in words if w.lower() not in self.stop_words]
        return " ".join(filtered)

    def normalize(self, query: str) -> str:
        """Normalize a query string.

        Args:
            query: Original query

        Returns:
            Normalized query
        """
        # Remove extra whitespace
        query = " ".join(query.split())

        # Remove very short words (unless in quotes)
        words = []
        in_quote = False
        current_word = []

        for char in query:
            if char in '"\'':
                in_quote = not in_quote
                current_word.append(char)
            elif char == " " and not in_quote:
                if current_word:
                    word = "".join(current_word)
                    if len(word) >= self.min_word_length or word.startswith('"'):
                        words.append(word)
                    current_word = []
            else:
                current_word.append(char)

        if current_word:
            word = "".join(current_word)
            if len(word) >= self.min_word_length or word.startswith('"'):
                words.append(word)

        return " ".join(words)


def parse_search_query(
    query: str,
    config: str = "english",
) -> ParsedQuery:
    """Convenience function to parse a search query.

    Args:
        query: User's search query
        config: PostgreSQL text search configuration

    Returns:
        ParsedQuery with parsed components
    """
    parser = SearchQueryParser(config=config)
    return parser.parse(query)


__all__ = [
    "TokenType",
    "Token",
    "ParsedQuery",
    "SearchQueryParser",
    "QueryRewriter",
    "parse_search_query",
]
