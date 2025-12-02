"""Search service for unified full-text search.

Provides a high-level interface for searching across multiple entity types
with PostgreSQL full-text search.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import (
    EntitySearchResult,
    SearchableEntity,
    SearchCapabilitiesResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchSuggestion,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Registry of searchable entities
# Maps entity type to configuration
SEARCHABLE_ENTITIES: dict[str, dict[str, Any]] = {
    "reminders": {
        "display_name": "Reminders",
        "model_path": "example_service.features.reminders.models.Reminder",
        "search_fields": ["title", "description"],
        "title_field": "title",
        "snippet_field": "description",
        "id_field": "id",
        "config": "english",
    },
    # Add more searchable entities here
}


class SearchService:
    """Unified search service for full-text search.

    Provides:
    - Multi-entity search with a single query
    - Result ranking and highlighting
    - Search suggestions/autocomplete
    - Configurable search syntax

    Example:
        service = SearchService(session)

        # Search across all entities
        results = await service.search(SearchRequest(
            query="important meeting",
            highlight=True,
        ))

        # Get suggestions for autocomplete
        suggestions = await service.suggest(SearchSuggestionRequest(
            prefix="imp",
        ))
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize search service.

        Args:
            session: Database session.
        """
        self.session = session

    def get_capabilities(self) -> SearchCapabilitiesResponse:
        """Get search capabilities and searchable entities.

        Returns:
            Description of search capabilities.
        """
        entities = []
        for name, config in SEARCHABLE_ENTITIES.items():
            entities.append(
                SearchableEntity(
                    name=name,
                    display_name=config["display_name"],
                    search_fields=config["search_fields"],
                    title_field=config.get("title_field"),
                    snippet_field=config.get("snippet_field"),
                )
            )

        return SearchCapabilitiesResponse(
            entities=entities,
            supported_syntax=list(SearchSyntax),
            max_query_length=500,
            max_results_per_entity=100,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a search across entity types.

        Args:
            request: Search request parameters.

        Returns:
            Search response with results and metadata.
        """
        start_time = time.monotonic()

        # Determine which entities to search
        entity_types = request.entity_types or list(SEARCHABLE_ENTITIES.keys())
        entity_types = [t for t in entity_types if t in SEARCHABLE_ENTITIES]

        if not entity_types:
            return SearchResponse(
                query=request.query,
                total_hits=0,
                results=[],
                took_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Search each entity type
        results: list[EntitySearchResult] = []
        total_hits = 0

        for entity_type in entity_types:
            entity_result = await self._search_entity(entity_type, request)
            results.append(entity_result)
            total_hits += entity_result.total

        # Generate suggestions if few results
        suggestions = []
        if total_hits < 3:
            suggestions = await self._generate_suggestions(request.query)

        took_ms = int((time.monotonic() - start_time) * 1000)

        return SearchResponse(
            query=request.query,
            total_hits=total_hits,
            results=results,
            suggestions=suggestions,
            took_ms=took_ms,
        )

    async def _search_entity(
        self,
        entity_type: str,
        request: SearchRequest,
    ) -> EntitySearchResult:
        """Search a specific entity type.

        Args:
            entity_type: Entity type to search.
            request: Search request.

        Returns:
            Search results for this entity type.
        """
        config = SEARCHABLE_ENTITIES[entity_type]
        model_class = self._import_model(config["model_path"])

        # Check if model has search_vector
        if not hasattr(model_class, "search_vector"):
            return EntitySearchResult(
                entity_type=entity_type,
                total=0,
                hits=[],
            )

        # Build tsquery based on syntax
        ts_config = config.get("config", "english")
        ts_query = self._build_tsquery(request.query, request.syntax, ts_config)

        # Build search query with rank
        search_vector = model_class.search_vector
        rank_expr = func.ts_rank(search_vector, ts_query)

        # Main query
        stmt = (
            select(
                model_class,
                rank_expr.label("rank"),
            )
            .where(search_vector.op("@@")(ts_query))
            .where(rank_expr >= request.min_rank)
            .order_by(rank_expr.desc())
            .offset(request.offset)
            .limit(request.limit)
        )

        # Execute search
        result = await self.session.execute(stmt)
        rows = result.all()

        # Get total count
        count_stmt = (
            select(func.count())
            .select_from(model_class)
            .where(search_vector.op("@@")(ts_query))
            .where(rank_expr >= request.min_rank)
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Build hits with optional highlighting
        hits = []
        for row in rows:
            entity = row[0]
            rank = float(row[1])

            # Get title
            title = None
            if config.get("title_field"):
                title = getattr(entity, config["title_field"], None)

            # Get snippet with highlighting
            snippet = None
            if request.highlight and config.get("snippet_field"):
                snippet = await self._get_highlighted_snippet(
                    entity_type,
                    entity,
                    request.query,
                    config.get("snippet_field"),
                    ts_config,
                    request.highlight_tag,
                )
            elif config.get("snippet_field"):
                snippet_text = getattr(entity, config["snippet_field"], None)
                if snippet_text:
                    snippet = snippet_text[:200] + "..." if len(snippet_text) > 200 else snippet_text

            # Build entity data
            entity_id = str(getattr(entity, config.get("id_field", "id")))
            created_at = getattr(entity, "created_at", None)

            # Get entity data as dict
            if hasattr(entity, "model_dump"):
                data = entity.model_dump()
            elif hasattr(entity, "__dict__"):
                data = {k: v for k, v in entity.__dict__.items() if not k.startswith("_")}
            else:
                data = {}

            hits.append(
                SearchHit(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    rank=rank,
                    title=str(title) if title else None,
                    snippet=snippet,
                    data=data,
                    created_at=created_at,
                )
            )

        return EntitySearchResult(
            entity_type=entity_type,
            total=total,
            hits=hits,
        )

    async def suggest(
        self,
        request: SearchSuggestionRequest,
    ) -> SearchSuggestionsResponse:
        """Get search suggestions for autocomplete.

        Uses prefix matching on searchable fields to provide
        suggestions as the user types.

        Args:
            request: Suggestion request.

        Returns:
            List of suggestions.
        """
        suggestions = []

        # Determine which entities to search
        if request.entity_type:
            entity_types = [request.entity_type]
        else:
            entity_types = list(SEARCHABLE_ENTITIES.keys())

        for entity_type in entity_types:
            if entity_type not in SEARCHABLE_ENTITIES:
                continue

            config = SEARCHABLE_ENTITIES[entity_type]
            model_class = self._import_model(config["model_path"])

            if not hasattr(model_class, "search_vector"):
                continue

            # Build prefix query
            ts_config = config.get("config", "english")
            # Add :* for prefix matching
            prefix_query = request.prefix + ":*"
            ts_query = func.to_tsquery(ts_config, prefix_query)

            # Get matching titles
            title_field = config.get("title_field")
            if not title_field or not hasattr(model_class, title_field):
                continue

            stmt = (
                select(
                    getattr(model_class, title_field),
                    func.count().label("count"),
                )
                .where(model_class.search_vector.op("@@")(ts_query))
                .group_by(getattr(model_class, title_field))
                .order_by(text("count DESC"))
                .limit(request.limit)
            )

            try:
                result = await self.session.execute(stmt)
                for row in result.all():
                    if row[0]:
                        suggestions.append(
                            SearchSuggestion(
                                text=str(row[0]),
                                entity_type=entity_type,
                                count=row[1],
                            )
                        )
            except Exception as e:
                logger.warning(f"Suggestion query failed for {entity_type}: {e}")
                continue

        # Sort by count and limit
        suggestions.sort(key=lambda s: s.count, reverse=True)
        suggestions = suggestions[: request.limit]

        return SearchSuggestionsResponse(
            prefix=request.prefix,
            suggestions=suggestions,
        )

    def _build_tsquery(
        self,
        query: str,
        syntax: SearchSyntax,
        config: str,
    ) -> Any:
        """Build PostgreSQL tsquery from search string.

        Args:
            query: User's search query.
            syntax: Query syntax mode.
            config: Text search configuration.

        Returns:
            SQLAlchemy tsquery expression.
        """
        if syntax == SearchSyntax.WEB:
            return func.websearch_to_tsquery(config, query)
        elif syntax == SearchSyntax.PHRASE:
            return func.phraseto_tsquery(config, query)
        else:  # PLAIN
            return func.plainto_tsquery(config, query)

    async def _get_highlighted_snippet(
        self,
        entity_type: str,
        entity: Any,
        query: str,
        snippet_field: str,
        config: str,
        highlight_tag: str,
    ) -> str | None:
        """Get highlighted snippet using PostgreSQL ts_headline.

        Args:
            entity_type: Entity type.
            entity: Entity instance.
            query: Search query.
            snippet_field: Field to use for snippet.
            config: Text search configuration.
            highlight_tag: HTML tag for highlights.

        Returns:
            Highlighted snippet or None.
        """
        text_value = getattr(entity, snippet_field, None)
        if not text_value:
            return None

        # Use ts_headline for highlighting
        close_tag = highlight_tag.replace("<", "</")
        options = f"StartSel={highlight_tag}, StopSel={close_tag}, MaxWords=35, MinWords=15"

        try:
            stmt = select(
                func.ts_headline(
                    config,
                    literal(str(text_value)),
                    func.websearch_to_tsquery(config, query),
                    options,
                )
            )
            result = await self.session.execute(stmt)
            snippet = result.scalar()
            return snippet if snippet else text_value[:200]
        except Exception as e:
            logger.debug(f"Highlighting failed: {e}")
            return text_value[:200] + "..." if len(text_value) > 200 else text_value

    async def _generate_suggestions(self, query: str) -> list[str]:
        """Generate query suggestions for low-result queries.

        Args:
            query: Original query.

        Returns:
            List of suggested queries.
        """
        suggestions = []

        # Simple suggestions based on query modifications
        words = query.split()
        if len(words) > 1:
            # Suggest individual words
            for word in words:
                if len(word) > 2:
                    suggestions.append(word)

        # Could add spell-check, synonyms, etc. here

        return suggestions[:5]

    def _import_model(self, model_path: str):
        """Dynamically import a model class.

        Args:
            model_path: Full module path to model.

        Returns:
            Model class.
        """
        parts = model_path.rsplit(".", 1)
        module_path, class_name = parts
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, class_name)


async def get_search_service(session: AsyncSession) -> SearchService:
    """Get a search service instance.

    Args:
        session: Database session.

    Returns:
        SearchService instance.
    """
    return SearchService(session)
