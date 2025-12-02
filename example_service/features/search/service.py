"""Search service for unified full-text search.

Provides a high-level interface for searching across multiple entity types
with PostgreSQL full-text search, including:
- Multi-entity search with a single query
- Result ranking and highlighting
- Search suggestions/autocomplete
- Fuzzy matching with pg_trgm
- "Did you mean?" suggestions
- Faceted search
- Search analytics
- Redis caching for frequent queries
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, literal, or_, select, text

from example_service.core.database.search import (
    RankNormalization,
    SearchAnalytics,
    SearchQueryParser,
)

from .cache import SearchCache, get_search_cache
from .schemas import (
    DidYouMeanSuggestion,
    EntitySearchResult,
    FacetResult,
    FacetValue,
    SearchableEntity,
    SearchAnalyticsRequest,
    SearchAnalyticsResponse,
    SearchCapabilitiesResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchSuggestion,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
    SearchTrendPoint,
    SearchTrendsResponse,
    ZeroResultQuery,
    ZeroResultsResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
        "fuzzy_fields": ["title"],  # Fields for fuzzy matching
        "facet_fields": ["is_completed"],  # Fields for faceted search
    },
    "posts": {
        "display_name": "Posts",
        "model_path": "example_service.core.models.post.Post",
        "search_fields": ["title", "content", "slug"],
        "title_field": "title",
        "snippet_field": "content",
        "id_field": "id",
        "config": "english",
        "fuzzy_fields": ["title"],
        "facet_fields": ["is_published", "author_id"],
    },
    "users": {
        "display_name": "Users",
        "model_path": "example_service.core.models.user.User",
        "search_fields": ["email", "username", "full_name"],
        "title_field": "username",
        "snippet_field": "full_name",
        "id_field": "id",
        "config": "simple",  # Use simple for identifiers
        "fuzzy_fields": ["username", "full_name"],
        "facet_fields": ["is_active"],
    },
}


class SearchService:
    """Unified search service for full-text search.

    Provides:
    - Multi-entity search with a single query
    - Result ranking and highlighting
    - Search suggestions/autocomplete
    - Configurable search syntax
    - Fuzzy matching fallback
    - "Did you mean?" suggestions
    - Faceted search results
    - Search analytics tracking

    Example:
        service = SearchService(session)

        # Search across all entities
        results = await service.search(SearchRequest(
            query="important meeting",
            highlight=True,
            include_facets=True,
        ))

        # Get suggestions for autocomplete
        suggestions = await service.suggest(SearchSuggestionRequest(
            prefix="imp",
        ))
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        enable_analytics: bool = True,
        enable_fuzzy_fallback: bool = True,
        enable_cache: bool = True,
        cache: SearchCache | None = None,
    ) -> None:
        """Initialize search service.

        Args:
            session: Database session.
            enable_analytics: Enable search analytics tracking.
            enable_fuzzy_fallback: Enable fuzzy search when FTS returns no results.
            enable_cache: Enable Redis caching for search results.
            cache: Optional pre-configured SearchCache instance.
        """
        self.session = session
        self.enable_analytics = enable_analytics
        self.enable_fuzzy_fallback = enable_fuzzy_fallback
        self.enable_cache = enable_cache
        self._query_parser = SearchQueryParser()
        self._analytics = SearchAnalytics(session) if enable_analytics else None
        self._cache = cache

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
                    supports_fuzzy=bool(config.get("fuzzy_fields")),
                    facet_fields=config.get("facet_fields", []),
                )
            )

        return SearchCapabilitiesResponse(
            entities=entities,
            supported_syntax=list(SearchSyntax),
            max_query_length=500,
            max_results_per_entity=100,
            features=[
                "full_text_search",
                "fuzzy_matching",
                "highlighting",
                "faceted_search",
                "autocomplete",
                "did_you_mean",
            ],
        )

    async def _get_cache(self) -> SearchCache | None:
        """Get the search cache instance.

        Returns:
            SearchCache if caching is enabled, None otherwise.
        """
        if not self.enable_cache:
            return None

        if self._cache:
            return self._cache

        # Try to get global cache instance
        self._cache = await get_search_cache()
        return self._cache

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a search across entity types.

        Args:
            request: Search request parameters.

        Returns:
            Search response with results and metadata.
        """
        start_time = time.monotonic()

        # Try to get cached results
        cache = await self._get_cache()
        if cache:
            cached = await cache.get_search_results(request)
            if cached:
                # Return cached response (add cache hit indicator to took_ms)
                return SearchResponse(
                    query=cached.get("query", request.query),
                    total_hits=cached.get("total_hits", 0),
                    results=[
                        EntitySearchResult(**r) for r in cached.get("results", [])
                    ],
                    suggestions=cached.get("suggestions", []),
                    did_you_mean=DidYouMeanSuggestion(**cached["did_you_mean"])
                    if cached.get("did_you_mean") else None,
                    facets=[FacetResult(**f) for f in cached.get("facets", [])]
                    if cached.get("facets") else None,
                    took_ms=0,  # Indicate cache hit with 0ms
                )

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
        all_facets: list[FacetResult] = []

        for entity_type in entity_types:
            entity_result = await self._search_entity(entity_type, request)
            results.append(entity_result)
            total_hits += entity_result.total

            # Collect facets
            if request.include_facets and entity_result.facets:
                all_facets.extend(entity_result.facets)

        # Generate "Did you mean?" suggestions for low/no results
        did_you_mean = None
        if total_hits < 3 and self.enable_fuzzy_fallback:
            did_you_mean = await self._generate_did_you_mean(request.query, entity_types)

        # Generate suggestions if few results
        suggestions = []
        if total_hits < 3:
            suggestions = await self._generate_suggestions(request.query)

        took_ms = int((time.monotonic() - start_time) * 1000)

        # Record analytics
        if self._analytics:
            try:
                await self._analytics.record_search(
                    query=request.query,
                    results_count=total_hits,
                    took_ms=took_ms,
                    entity_types=entity_types,
                    search_syntax=request.syntax.value,
                )
            except Exception as e:
                logger.warning(f"Failed to record search analytics: {e}")

        response = SearchResponse(
            query=request.query,
            total_hits=total_hits,
            results=results,
            suggestions=suggestions,
            did_you_mean=did_you_mean,
            facets=all_facets if request.include_facets else None,
            took_ms=took_ms,
        )

        # Cache the results
        if cache:
            try:
                await cache.set_search_results(request, response)
            except Exception as e:
                logger.warning(f"Failed to cache search results: {e}")

        return response

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

        # Use ts_rank_cd for better phrase proximity ranking
        if request.syntax == SearchSyntax.PHRASE:
            rank_expr = func.ts_rank_cd(
                search_vector,
                ts_query,
                RankNormalization.SELF_PLUS_ONE,
            )
        else:
            rank_expr = func.ts_rank(
                search_vector,
                ts_query,
                RankNormalization.SELF_PLUS_ONE,
            )

        # Main query
        stmt = (
            select( # type: ignore
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

        # If no FTS results and fuzzy is enabled, try fuzzy search
        if not rows and self.enable_fuzzy_fallback and config.get("fuzzy_fields"):
            rows = await self._fuzzy_search(model_class, config, request)

        # Get total count
        count_stmt = (
            select(func.count())
            .select_from(model_class) # type: ignore
            .where(search_vector.op("@@")(ts_query))
            .where(rank_expr >= request.min_rank)
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Build hits with optional highlighting
        hits = []
        for row in rows:
            entity = row[0] if isinstance(row, tuple) else row
            rank = float(row[1]) if isinstance(row, tuple) and len(row) > 1 else 0.5

            # Get title
            title = None
            if config.get("title_field"):
                title = getattr(entity, config["title_field"], None)

            # Get snippet with highlighting
            snippet = None
            if request.highlight and config.get("snippet_field"):
                snippet = await self._get_highlighted_snippet(
                    entity,
                    request.query,
                    config.get("snippet_field"), # type: ignore
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

            # Remove search_vector from data (it's not serializable)
            data.pop("search_vector", None)

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

        # Get facets if requested
        facets = None
        if request.include_facets and config.get("facet_fields"):
            facets = await self._get_facets(
                model_class,
                config,
                ts_query,
                search_vector,
            )

        return EntitySearchResult(
            entity_type=entity_type,
            total=total,
            hits=hits,
            facets=facets,
        )

    async def _fuzzy_search(
        self,
        model_class: Any,
        config: dict[str, Any],
        request: SearchRequest,
    ) -> list[Any]:
        """Perform fuzzy search as fallback.

        Args:
            model_class: SQLAlchemy model class.
            config: Entity configuration.
            request: Search request.

        Returns:
            List of (entity, rank) tuples.
        """
        fuzzy_fields = config.get("fuzzy_fields", [])
        if not fuzzy_fields:
            return []

        conditions = []
        similarities = []

        for field_name in fuzzy_fields:
            if hasattr(model_class, field_name):
                field = getattr(model_class, field_name)
                # Use word_similarity for better matching in longer text
                conditions.append(field.op("%")(request.query))
                similarities.append(func.similarity(request.query, field))

        if not conditions:
            return []

        # Get max similarity across fields
        max_sim = similarities[0] if len(similarities) == 1 else func.greatest(*similarities)

        stmt = (
            select(model_class, max_sim.label("rank"))
            .where(or_(*conditions))
            .order_by(max_sim.desc())
            .offset(request.offset)
            .limit(request.limit)
        )

        try:
            result = await self.session.execute(stmt)
            return result.all() # type: ignore
        except Exception as e:
            logger.warning(f"Fuzzy search failed: {e}")
            return []

    async def _get_facets(
        self,
        model_class: Any,
        config: dict[str, Any],
        ts_query: Any,
        search_vector: Any,
    ) -> list[FacetResult]:
        """Get facet counts for search results.

        Args:
            model_class: SQLAlchemy model class.
            config: Entity configuration.
            ts_query: The tsquery for filtering.
            search_vector: The search vector column.

        Returns:
            List of facet results.
        """
        facets = []
        facet_fields = config.get("facet_fields", [])

        for field_name in facet_fields:
            if not hasattr(model_class, field_name):
                continue

            field = getattr(model_class, field_name)

            # Get value counts
            stmt = (
                select(field, func.count().label("count"))
                .where(search_vector.op("@@")(ts_query))
                .group_by(field)
                .order_by(text("count DESC"))
                .limit(20)
            )

            try:
                result = await self.session.execute(stmt)
                values = [
                    FacetValue(value=str(row[0]) if row[0] is not None else "null", count=row[1])
                    for row in result.all()
                ]

                if values:
                    facets.append(
                        FacetResult(
                            field=field_name,
                            display_name=field_name.replace("_", " ").title(),
                            values=values,
                        )
                    )
            except Exception as e:
                logger.warning(f"Facet query failed for {field_name}: {e}")

        return facets

    async def _generate_did_you_mean(
        self,
        query: str,
        entity_types: list[str],
    ) -> DidYouMeanSuggestion | None:
        """Generate "Did you mean?" suggestion using fuzzy matching.

        Args:
            query: Original query.
            entity_types: Entity types to search.

        Returns:
            Suggestion if found, None otherwise.
        """
        best_suggestion = None
        best_similarity = 0.0

        for entity_type in entity_types:
            if entity_type not in SEARCHABLE_ENTITIES:
                continue

            config = SEARCHABLE_ENTITIES[entity_type]
            model_class = self._import_model(config["model_path"])
            fuzzy_fields = config.get("fuzzy_fields", [])

            for field_name in fuzzy_fields:
                if not hasattr(model_class, field_name):
                    continue

                field = getattr(model_class, field_name)

                # Find similar values
                stmt = (
                    select(
                        field,
                        func.similarity(query, field).label("sim"),
                    )
                    .where(field.op("%")(query))
                    .order_by(text("sim DESC"))
                    .limit(1)
                )

                try:
                    result = await self.session.execute(stmt)
                    row = result.first()
                    if row and row[1] > best_similarity and row[1] > 0.3:
                        best_similarity = row[1]
                        best_suggestion = str(row[0])
                except Exception as e:
                    logger.debug(f"Did you mean query failed: {e}")

        if best_suggestion and best_suggestion.lower() != query.lower():
            return DidYouMeanSuggestion(
                original_query=query,
                suggested_query=best_suggestion,
                confidence=best_similarity,
            )

        return None

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

            try:
                ts_query = func.to_tsquery(ts_config, prefix_query)
            except Exception:
                # Fall back to plain text query if prefix query fails
                ts_query = func.plainto_tsquery(ts_config, request.prefix)

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
        entity: Any,
        query: str,
        snippet_field: str,
        config: str,
        highlight_tag: str,
    ) -> str | None:
        """Get highlighted snippet using PostgreSQL ts_headline.

        Args:
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
        options = f"StartSel={highlight_tag}, StopSel={close_tag}, MaxWords=35, MinWords=15, ShortWord=3, HighlightAll=FALSE"

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
            return snippet if snippet else text_value[:200] # type: ignore
        except Exception as e:
            logger.debug(f"Highlighting failed: {e}")
            return text_value[:200] + "..." if len(text_value) > 200 else text_value # type: ignore

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

        return suggestions[:5]

    def _import_model(self, model_path: str) -> str:
        """Dynamically import a model class.

        Args:
            model_path: Full module path to model.

        Returns:
            Model class.
        """
        parts = model_path.rsplit(".", 1)
        module_path, class_name = parts

        module = importlib.import_module(module_path)
        return getattr(module, class_name) # type: ignore

    # ──────────────────────────────────────────────────────────────
    # Analytics Methods
    # ──────────────────────────────────────────────────────────────

    async def get_analytics(
        self,
        request: SearchAnalyticsRequest,
    ) -> SearchAnalyticsResponse:
        """Get search analytics summary.

        Args:
            request: Analytics request with time period.

        Returns:
            Analytics response with stats and insights.
        """
        if not self._analytics:
            self._analytics = SearchAnalytics(self.session)

        stats = await self._analytics.get_stats(days=request.days)

        return SearchAnalyticsResponse(
            total_searches=stats.total_searches,
            unique_queries=stats.unique_queries,
            zero_result_rate=stats.zero_result_rate,
            avg_results_count=stats.avg_results_count,
            avg_response_time_ms=stats.avg_response_time_ms,
            click_through_rate=stats.click_through_rate,
            top_queries=stats.top_queries,
            zero_result_queries=stats.zero_result_queries,
            period_days=request.days,
        )

    async def get_trends(
        self,
        days: int = 30,
        interval: str = "day",
    ) -> SearchTrendsResponse:
        """Get search trends over time.

        Args:
            days: Number of days to analyze.
            interval: Time grouping interval.

        Returns:
            Trends response with time series data.
        """
        if not self._analytics:
            self._analytics = SearchAnalytics(self.session)

        trends_data = await self._analytics.get_search_trends(
            days=days,
            interval=interval,
        )

        # Convert to response format
        trends = [
            SearchTrendPoint(
                period=t["period"] or "",
                count=t["count"],
                unique_queries=t["unique_queries"],
                zero_results=t["zero_results"],
            )
            for t in trends_data
        ]

        total_searches = sum(t.count for t in trends)
        avg_daily = total_searches / days if days > 0 else 0

        return SearchTrendsResponse(
            interval=interval,
            days=days,
            trends=trends,
            total_searches=total_searches,
            avg_daily_searches=round(avg_daily, 2),
        )

    async def get_zero_result_queries(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> ZeroResultsResponse:
        """Get queries that returned no results.

        Args:
            days: Number of days to analyze.
            limit: Maximum queries to return.

        Returns:
            Zero-results response with content gap information.
        """
        if not self._analytics:
            self._analytics = SearchAnalytics(self.session)

        zero_results = await self._analytics.get_zero_result_queries(
            days=days,
            limit=limit,
        )

        queries = [
            ZeroResultQuery(
                query=q["query"] or "",
                count=q["count"],
            )
            for q in zero_results
        ]

        total_zero = sum(q.count for q in queries)

        # Generate recommendations based on zero-result patterns
        recommendations = []
        if queries:
            recommendations.append(
                "Consider adding content that addresses these frequently searched topics."
            )
            recommendations.append(
                "Review if synonyms could help match these queries to existing content."
            )
            if any(len(q.query.split()) == 1 for q in queries):
                recommendations.append(
                    "Some single-word queries may benefit from fuzzy matching improvements."
                )

        return ZeroResultsResponse(
            days=days,
            total_zero_result_searches=total_zero,
            queries=queries,
            recommendations=recommendations,
        )

    async def record_click(
        self,
        search_id: int,
        clicked_position: int,
        clicked_entity_id: str,
    ) -> None:
        """Record a click on a search result.

        Args:
            search_id: ID of the search query record.
            clicked_position: Position of clicked result.
            clicked_entity_id: ID of the clicked entity.
        """
        if not self._analytics:
            self._analytics = SearchAnalytics(self.session)

        await self._analytics.record_click(
            search_id=search_id,
            clicked_position=clicked_position,
            clicked_entity_id=clicked_entity_id,
        )


async def get_search_service(
    session: AsyncSession,
    enable_analytics: bool = True,
) -> SearchService:
    """Get a search service instance.

    Args:
        session: Database session.
        enable_analytics: Enable search analytics tracking.

    Returns:
        SearchService instance.
    """
    return SearchService(session, enable_analytics=enable_analytics)
