"""Synonym dictionary support for PostgreSQL full-text search.

Provides a configurable thesaurus system for domain-specific synonyms
to improve search recall and relevance.

Features:
- Load synonyms from files or dictionaries
- Bidirectional synonym expansion
- Domain-specific thesaurus groups
- Integration with PostgreSQL's dictionary system
- Query rewriting for synonym expansion

Usage:
    from example_service.core.database.search.synonyms import (
        SynonymDictionary,
        load_synonyms_from_file,
    )

    # Create dictionary with programming synonyms
    synonyms = SynonymDictionary()
    synonyms.add_group(["python", "py", "python3"])
    synonyms.add_group(["javascript", "js", "ecmascript"])

    # Expand a query
    expanded = synonyms.expand_query("py tutorial")
    # Returns: "(python OR py OR python3) tutorial"

    # Generate PostgreSQL thesaurus file
    synonyms.to_thesaurus_file("/path/to/thesaurus.ths")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SynonymGroup:
    """A group of synonymous terms.

    Attributes:
        terms: List of synonymous terms.
        canonical: The preferred/canonical term (first by default).
        bidirectional: Whether synonyms expand in both directions.
        weight: Relative importance of this group.
    """

    terms: list[str]
    canonical: str | None = None
    bidirectional: bool = True
    weight: float = 1.0

    def __post_init__(self):
        """Set canonical term if not specified."""
        if self.canonical is None and self.terms:
            self.canonical = self.terms[0]


@dataclass
class SynonymDictionary:
    """A dictionary of synonyms for query expansion.

    Supports loading from files, adding synonyms programmatically,
    and generating PostgreSQL thesaurus files.

    Example:
        # Create and populate dictionary
        synonyms = SynonymDictionary(name="programming")

        # Add synonym groups
        synonyms.add_group(["python", "py", "python3"])
        synonyms.add_group(["database", "db", "datastore"])
        synonyms.add_pair("api", "interface")

        # Expand a search query
        query = "py db tutorial"
        expanded = synonyms.expand_query(query)
        # "(python OR py OR python3) (database OR db OR datastore) tutorial"
    """

    name: str = "default"
    groups: list[SynonymGroup] = field(default_factory=list)
    _index: dict[str, SynonymGroup] = field(default_factory=dict, repr=False)

    def add_group(
        self,
        terms: list[str],
        canonical: str | None = None,
        bidirectional: bool = True,
        weight: float = 1.0,
    ) -> None:
        """Add a synonym group.

        Args:
            terms: List of synonymous terms.
            canonical: Preferred term (first term if not specified).
            bidirectional: Whether to expand in both directions.
            weight: Relative importance of this group.
        """
        # Normalize terms
        normalized = [t.lower().strip() for t in terms if t.strip()]
        if len(normalized) < 2:
            return  # Need at least 2 terms for synonyms

        group = SynonymGroup(
            terms=normalized,
            canonical=canonical.lower() if canonical else None,
            bidirectional=bidirectional,
            weight=weight,
        )

        self.groups.append(group)

        # Index terms for fast lookup
        for term in normalized:
            self._index[term] = group

    def add_pair(
        self,
        term1: str,
        term2: str,
        bidirectional: bool = True,
    ) -> None:
        """Add a synonym pair.

        Args:
            term1: First term.
            term2: Second term.
            bidirectional: Whether to expand in both directions.
        """
        self.add_group([term1, term2], bidirectional=bidirectional)

    def add_alias(self, alias: str, canonical: str) -> None:
        """Add an alias that expands to a canonical term.

        Args:
            alias: Alias term (e.g., "py").
            canonical: Canonical term (e.g., "python").
        """
        self.add_group(
            [canonical, alias],
            canonical=canonical,
            bidirectional=False,
        )

    def get_synonyms(self, term: str) -> list[str]:
        """Get all synonyms for a term.

        Args:
            term: Term to look up.

        Returns:
            List of synonyms (including the original term).
        """
        normalized = term.lower().strip()
        group = self._index.get(normalized)

        if group:
            return group.terms
        return [normalized]

    def expand_term(self, term: str) -> str:
        """Expand a term to include synonyms.

        Args:
            term: Term to expand.

        Returns:
            Expanded term with OR syntax.
        """
        synonyms = self.get_synonyms(term)

        if len(synonyms) > 1:
            return f"({' OR '.join(synonyms)})"
        return term

    def expand_query(self, query: str) -> str:
        """Expand a full query to include synonyms.

        Preserves quoted phrases and operators.

        Args:
            query: Search query.

        Returns:
            Expanded query with synonyms.
        """
        # Pattern to match quoted phrases
        phrase_pattern = re.compile(r'["\']([^"\']+)["\']')

        # Extract and protect quoted phrases
        phrases = {}
        idx = 0

        def replace_phrase(match):
            nonlocal idx
            placeholder = f"__PHRASE_{idx}__"
            phrases[placeholder] = match.group(0)
            idx += 1
            return placeholder

        protected = phrase_pattern.sub(replace_phrase, query)

        # Split into words and operators
        words = protected.split()
        expanded = []

        for word in words:
            # Preserve operators and placeholders
            if word.upper() in ("AND", "OR", "NOT") or word.startswith("__PHRASE_"):
                expanded.append(word)
            elif word.startswith("-"):
                # Preserve exclusions
                expanded.append(word)
            elif ":" in word:
                # Preserve field queries
                expanded.append(word)
            else:
                expanded.append(self.expand_term(word))

        result = " ".join(expanded)

        # Restore quoted phrases
        for placeholder, phrase in phrases.items():
            result = result.replace(placeholder, phrase)

        return result

    def to_dict(self) -> dict[str, list[str]]:
        """Convert to a simple dictionary mapping.

        Returns:
            Dictionary mapping terms to their synonyms.
        """
        result = {}
        for group in self.groups:
            for term in group.terms:
                result[term] = group.terms
        return result

    def to_thesaurus_file(self, path: str | Path) -> None:
        """Generate a PostgreSQL thesaurus file.

        The file can be used with PostgreSQL's thesaurus dictionary.

        Args:
            path: Output file path.
        """
        path = Path(path)
        lines = []

        # Add header
        lines.append("# PostgreSQL Thesaurus File")
        lines.append(f"# Dictionary: {self.name}")
        lines.append("")

        for group in self.groups:
            if group.bidirectional:
                # All terms map to canonical
                canonical = group.canonical or group.terms[0]
                for term in group.terms:
                    if term != canonical:
                        lines.append(f"{term} : {canonical}")
            else:
                # Only non-canonical terms map to canonical
                canonical = group.canonical or group.terms[0]
                for term in group.terms:
                    if term != canonical:
                        lines.append(f"{term} : {canonical}")

        path.write_text("\n".join(lines))
        logger.info(f"Written thesaurus file to {path}")

    @classmethod
    def from_dict(
        cls,
        data: dict[str, list[str]],
        name: str = "default",
    ) -> "SynonymDictionary":
        """Create dictionary from a simple mapping.

        Args:
            data: Dictionary mapping canonical terms to aliases.
            name: Dictionary name.

        Returns:
            SynonymDictionary instance.
        """
        synonyms = cls(name=name)

        for canonical, aliases in data.items():
            synonyms.add_group([canonical] + aliases, canonical=canonical)

        return synonyms

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        name: str | None = None,
    ) -> "SynonymDictionary":
        """Load synonyms from a file.

        Supports formats:
        - Simple: term1, term2, term3  (one group per line)
        - Thesaurus: term1 : canonical
        - JSON: {"canonical": ["alias1", "alias2"]}

        Args:
            path: File path.
            name: Dictionary name (defaults to filename).

        Returns:
            SynonymDictionary instance.
        """
        path = Path(path)
        name = name or path.stem

        synonyms = cls(name=name)

        content = path.read_text()

        # Try JSON first
        if path.suffix == ".json":
            import json
            data = json.loads(content)
            return cls.from_dict(data, name=name)

        # Parse line-based format
        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Thesaurus format: term : canonical
            if ":" in line:
                parts = [p.strip() for p in line.split(":")]
                if len(parts) == 2:
                    synonyms.add_alias(parts[0], parts[1])
            # Simple format: term1, term2, term3
            elif "," in line:
                terms = [t.strip() for t in line.split(",")]
                synonyms.add_group(terms)
            # Space-separated
            else:
                terms = line.split()
                if len(terms) >= 2:
                    synonyms.add_group(terms)

        return synonyms


# Default programming/tech synonyms
DEFAULT_PROGRAMMING_SYNONYMS: dict[str, list[str]] = {
    "python": ["py", "python3"],
    "javascript": ["js", "ecmascript", "es6", "es2015"],
    "typescript": ["ts"],
    "database": ["db", "datastore"],
    "api": ["interface", "endpoint"],
    "function": ["func", "fn", "method"],
    "repository": ["repo"],
    "configuration": ["config", "cfg", "settings"],
    "documentation": ["docs", "readme"],
    "authentication": ["auth", "login"],
    "authorization": ["authz", "permissions"],
    "administrator": ["admin"],
    "development": ["dev"],
    "production": ["prod"],
    "environment": ["env"],
    "application": ["app"],
    "container": ["docker", "pod"],
    "kubernetes": ["k8s"],
    "postgresql": ["postgres", "pg"],
    "elasticsearch": ["es", "elastic"],
    "redis": ["cache"],
    "message": ["msg"],
    "error": ["err", "exception"],
    "warning": ["warn"],
    "information": ["info"],
    "debug": ["dbg"],
}


def get_default_synonyms() -> SynonymDictionary:
    """Get the default programming synonyms dictionary.

    Returns:
        SynonymDictionary with common tech synonyms.
    """
    return SynonymDictionary.from_dict(
        DEFAULT_PROGRAMMING_SYNONYMS,
        name="programming",
    )


def create_synonym_config_sql(
    config_name: str,
    base_config: str = "english",
    thesaurus_file: str | None = None,
) -> str:
    """Generate SQL to create a custom text search configuration with synonyms.

    Args:
        config_name: Name for the new configuration.
        base_config: Base configuration to copy from.
        thesaurus_file: Path to thesaurus file (optional).

    Returns:
        SQL statements to create the configuration.
    """
    sql_parts = []

    # Create the configuration
    sql_parts.append(f"""
-- Create custom text search configuration
DROP TEXT SEARCH CONFIGURATION IF EXISTS {config_name} CASCADE;
CREATE TEXT SEARCH CONFIGURATION {config_name} (COPY = {base_config});
""")

    # Add thesaurus dictionary if file provided
    if thesaurus_file:
        sql_parts.append(f"""
-- Create thesaurus dictionary
DROP TEXT SEARCH DICTIONARY IF EXISTS {config_name}_thesaurus CASCADE;
CREATE TEXT SEARCH DICTIONARY {config_name}_thesaurus (
    TEMPLATE = thesaurus,
    DictFile = {thesaurus_file},
    Dictionary = {base_config}_stem
);

-- Add thesaurus to configuration
ALTER TEXT SEARCH CONFIGURATION {config_name}
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
    WITH {config_name}_thesaurus, {base_config}_stem;
""")

    return "\n".join(sql_parts)


def create_synonym_dictionary_sql(
    dict_name: str,
    synonyms: dict[str, list[str]],
) -> str:
    """Generate SQL to create a simple synonym dictionary.

    This uses PostgreSQL's simple dictionary for basic synonym support.

    Args:
        dict_name: Name for the dictionary.
        synonyms: Dictionary mapping canonical terms to aliases.

    Returns:
        SQL statements.
    """
    # Generate synonym file content
    syn_entries = []
    for canonical, aliases in synonyms.items():
        for alias in aliases:
            syn_entries.append(f"{alias} {canonical}")

    syn_content = "\n".join(syn_entries)

    return f"""
-- Note: This requires writing the synonym file to the PostgreSQL data directory
-- Content for {dict_name}.syn:
/*
{syn_content}
*/

-- Create synonym dictionary
DROP TEXT SEARCH DICTIONARY IF EXISTS {dict_name} CASCADE;
CREATE TEXT SEARCH DICTIONARY {dict_name} (
    TEMPLATE = synonym,
    SYNONYMS = {dict_name}
);
"""


__all__ = [
    "SynonymGroup",
    "SynonymDictionary",
    "DEFAULT_PROGRAMMING_SYNONYMS",
    "get_default_synonyms",
    "create_synonym_config_sql",
    "create_synonym_dictionary_sql",
]
