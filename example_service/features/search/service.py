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
- Synonym expansion for improved recall
- Click signal boosting for improved ranking
- Query intent classification
- Performance profiling
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, literal, or_, select, text

from example_service.core.database.search import (
    QueryRewriter,
    RankNormalization,
    SearchAnalytics,
    SearchQueryParser,
    get_default_synonyms,
)

from .cache import SearchCache, get_search_cache
from .circuit_breaker import CircuitBreaker, get_circuit_breaker
from .config import (
    EntitySearchConfig,
    SearchConfiguration,
    SearchEntityRegistry,
    get_search_config,
)
from .intent import IntentClassifier, IntentType, QueryIntent
from .profiler import QueryProfiler
from .ranking import ClickBoostRanker, RankingConfig
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
    - Synonym expansion for improved recall
    - Click signal boosting for ranking
    - Query intent classification
    - Performance profiling

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
        config: SearchConfiguration | None = None,
        enable_analytics: bool = True,
        enable_fuzzy_fallback: bool = True,
        enable_cache: bool = True,
        enable_synonyms: bool = True,
        enable_click_boosting: bool = True,
        enable_intent_classification: bool = False,
        enable_profiling: bool = True,
        cache: SearchCache | None = None,
    ) -> None:
        """Initialize search service.

        Args:
            session: Database session.
            config: Search configuration (uses global if not provided).
            enable_analytics: Enable search analytics tracking.
            enable_fuzzy_fallback: Enable fuzzy search when FTS returns no results.
            enable_cache: Enable Redis caching for search results.
            enable_synonyms: Enable synonym expansion for queries.
            enable_click_boosting: Enable click signal boosting for ranking.
            enable_intent_classification: Enable query intent classification.
            enable_profiling: Enable query performance profiling.
            cache: Optional pre-configured SearchCache instance.
        """
        self.session = session
        self._config = config or get_search_config()

        # Feature flags (override config if explicitly set)
        self.enable_analytics = enable_analytics
        self.enable_fuzzy_fallback = enable_fuzzy_fallback
        self.enable_cache = enable_cache
        self.enable_synonyms = enable_synonyms and self._config.settings.enable_synonyms
        self.enable_click_boosting = enable_click_boosting and self._config.settings.enable_click_boosting
        self.enable_intent_classification = (
            enable_intent_classification or self._config.settings.enable_intent_classification
        )
        self.enable_profiling = enable_profiling and self._config.settings.enable_query_profiling

        # Core components
        self._query_parser = SearchQueryParser()
        self._analytics = SearchAnalytics(session) if enable_analytics else None
        self._cache = cache

        # Enhanced components
        self._query_rewriter: QueryRewriter | None = None
        if self.enable_synonyms and self._config.synonym_dictionary:
            self._query_rewriter = QueryRewriter.with_dictionary(self._config.synonym_dictionary)

        self._click_ranker: ClickBoostRanker | None = None
        if self.enable_click_boosting:
            self._click_ranker = ClickBoostRanker(
                session,
                RankingConfig(
                    enable_click_boost=True,
                    click_boost_weight=self._config.settings.click_boost_weight,
                    min_clicks_for_boost=self._config.settings.min_clicks_for_boost,
                    click_decay_days=self._config.settings.click_decay_days,
                ),
            )

        self._intent_classifier: IntentClassifier | None = None
        if self.enable_intent_classification:
            self._intent_classifier = IntentClassifier()

        self._profiler: QueryProfiler | None = None
        if self.enable_profiling:
            self._profiler = QueryProfiler(
                session,
                slow_threshold_ms=self._config.settings.slow_query_threshold_ms,
            )

        # Circuit breaker for cache
        self._cache_circuit_breaker = get_circuit_breaker(
            "search_cache",
            threshold=self._config.settings.circuit_breaker_threshold,
            timeout=self._config.settings.circuit_breaker_timeout,
        )

    @property
    def entity_registry(self) -> SearchEntityRegistry:
        """Get the entity registry."""
        return self._config.entity_registry

    def get_capabilities(self) -> SearchCapabilitiesResponse:
        """Get search capabilities and searchable entities.

        Returns:
            Description of search capabilities.
        """
        entities = []
        for name in self._config.entity_registry.list_entities():
            config = self._config.entity_registry.get(name)
            if config:
                entities.append(
                    SearchableEntity(
                        name=name,
                        display_name=config.display_name,
                        search_fields=config.search_fields,
                        title_field=config.title_field,
                        snippet_field=config.snippet_field,
                        supports_fuzzy=bool(config.fuzzy_fields),
                        facet_fields=config.facet_fields,
                    )
                )

        return SearchCapabilitiesResponse(
            entities=entities,
            supported_syntax=list(SearchSyntax),
            max_query_length=self._config.settings.max_query_length,
            max_results_per_entity=self._config.settings.max_results_per_entity,
            features=self._config.get_enabled_features(),
        )

    async def _get_cache(self) -> SearchCache | None:
        """Get the search cache instance with circuit breaker protection.

        Returns:
            SearchCache if caching is enabled and circuit is closed, None otherwise.
        """
        if not self.enable_cache:
            return None

        # Check circuit breaker
        if not self._cache_circuit_breaker.can_execute():
            logger.debug("Cache circuit breaker is open, skipping cache")
            return None

        if self._cache:
            return self._cache

        # Try to get global cache instance
        try:
            self._cache = await get_search_cache()
            self._cache_circuit_breaker.record_success()
            return self._cache
        except Exception as e:
            self._cache_circuit_breaker.record_failure()
            logger.warning("Failed to get search cache: %s", e)
            return None

    def _expand_query_with_synonyms(self, query: str) -> str:
        """Expand query with synonyms for improved recall.

        Args:
            query: Original query.

        Returns:
            Expanded query with synonyms.
        """
        if not self.enable_synonyms or not self._query_rewriter:
            return query

        try:
            expanded = self._query_rewriter.expand_synonyms(query)
            if expanded != query:
                logger.debug("Query expanded with synonyms: '%s' -> '%s'", query, expanded)
            return expanded
        except Exception as e:
            logger.warning("Failed to expand query with synonyms: %s", e)
            return query

    def _classify_intent(self, query: str) -> QueryIntent | None:
        """Classify the intent of a search query.

        Args:
            query: Search query.

        Returns:
            QueryIntent or None if classification is disabled.
        """
        if not self.enable_intent_classification or not self._intent_classifier:
            return None

        try:
            return self._intent_classifier.classify(query)
        except Exception as e:
            logger.warning("Failed to classify query intent: %s", e)
            return None

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a search across entity types.

        Args:
            request: Search request parameters.

        Returns:
            Search response with results and metadata.
        """
        start_time = time.monotonic()

        # Profile the search if enabled
        profile_ctx = None
        if self._profiler:
            profile_ctx = self._profiler.profile("fts_search")
            await profile_ctx.__aenter__()
            profile_ctx.gen.set_query(request.query)

        try:
            return await self._execute_search(request, start_time)
        finally:
            if profile_ctx:
                await profile_ctx.__aexit__(None, None, None)

    async def _execute_search(
        self,
        request: SearchRequest,
        start_time: float,
    ) -> SearchResponse:
        """Execute the search operation.

        Args:
            request: Search request.
            start_time: Start timestamp.

        Returns:
            Search response.
        """
        # Classify intent (for adjustments)
        intent = self._classify_intent(request.query)

        # Try to get cached results
        cache = await self._get_cache()
        if cache:
            try:
                cached = await cache.get_search_results(request)
                if cached:
                    self._cache_circuit_breaker.record_success()
                    # Return cached response (add cache hit indicator to took_ms)
                    return SearchResponse(
                        query=cached.get("query", request.query),
                        total_hits=cached.get("total_hits", 0),
                        results=[
                            EntitySearchResult(**r) for r in cached.get("results", [])
                        ],
                        suggestions=cached.get("suggestions", []),
                        did_you_mean=DidYouMeanSuggestion(**cached["did_you_mean"])
                        if cached.get("did_you_mean")
                        else None,
                        facets=[FacetResult(**f) for f in cached.get("facets", [])]
                        if cached.get("facets")
                        else None,
                        took_ms=0,  # Indicate cache hit with 0ms
                    )
            except Exception as e:
                self._cache_circuit_breaker.record_failure()
                logger.warning("Cache get failed: %s", e)

        # Expand query with synonyms if enabled
        expanded_query = self._expand_query_with_synonyms(request.query)

        # Determine which entities to search
        entity_types = request.entity_types or self._config.entity_registry.list_entities()
        entity_types = [t for t in entity_types if self._config.entity_registry.get(t)]

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

        # Collect all entity IDs for batch click boost
        all_entity_ids: dict[str, list[str]] = {}

        for entity_type in entity_types:
            entity_result = await self._search_entity(
                entity_type,
                request,
                expanded_query,
                intent,
            )
            results.append(entity_result)
            total_hits += entity_result.total

            # Collect entity IDs
            all_entity_ids[entity_type] = [hit.entity_id for hit in entity_result.hits]

            # Collect facets
            if request.include_facets and entity_result.facets:
                all_facets.extend(entity_result.facets)

        # Apply click boosting if enabled
        if self.enable_click_boosting and self._click_ranker:
            results = await self._apply_click_boosting(results, all_entity_ids)

        # Generate "Did you mean?" suggestions for low/no results
        did_you_mean = None
        if total_hits < 3 and self.enable_fuzzy_fallback:
            did_you_mean = await self._generate_did_you_mean(
                request.query, entity_types
            )

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
                logger.warning("Failed to record search analytics: %s", e)

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
                self._cache_circuit_breaker.record_success()
            except Exception as e:
                self._cache_circuit_breaker.record_failure()
                logger.warning("Failed to cache search results: %s", e)

        return response

    async def _apply_click_boosting(
        self,
        results: list[EntitySearchResult],
        entity_ids: dict[str, list[str]],
    ) -> list[EntitySearchResult]:
        """Apply click boosting to search results.

        Args:
            results: Search results to boost.
            entity_ids: Entity IDs by type.

        Returns:
            Results with adjusted rankings.
        """
        if not self._click_ranker:
            return results

        boosted_results = []

        for entity_result in results:
            entity_type = entity_result.entity_type
            ids = entity_ids.get(entity_type, [])

            if not ids:
                boosted_results.append(entity_result)
                continue

            # Get batch click boosts
            boosts = await self._click_ranker.get_batch_click_boosts(entity_type, ids)

            # Apply boosts to hits
            boosted_hits = []
            for hit in entity_result.hits:
                boost = boosts.get(hit.entity_id, 0.0)
                adjusted_rank = self._click_ranker.calculate_final_rank(
                    hit.rank,
                    entity_type,
                    click_boost=boost,
                )
                boosted_hits.append(
                    SearchHit(
                        entity_type=hit.entity_type,
                        entity_id=hit.entity_id,
                        rank=adjusted_rank,
                        title=hit.title,
                        snippet=hit.snippet,
                        data=hit.data,
                        created_at=hit.created_at,
                    )
                )

            # Re-sort by adjusted rank
            boosted_hits.sort(key=lambda h: h.rank, reverse=True)

            boosted_results.append(
                EntitySearchResult(
                    entity_type=entity_type,
                    total=entity_result.total,
                    hits=boosted_hits,
                    facets=entity_result.facets,
                )
            )

        return boosted_results

    async def _search_entity(
        self,
        entity_type: str,
        request: SearchRequest,
        expanded_query: str,
        intent: QueryIntent | None,
    ) -> EntitySearchResult:
        """Search a specific entity type.

        Args:
            entity_type: Entity type to search.
            request: Search request.
            expanded_query: Query with synonym expansion.
            intent: Classified query intent.

        Returns:
            Search results for this entity type.
        """
        config = self._config.entity_registry.get(entity_type)
        if not config:
            return EntitySearchResult(entity_type=entity_type, total=0, hits=[])

        model_class = self._import_model(config.model_path)

        # Check if model has search_vector
        if not hasattr(model_class, "search_vector"):
            return EntitySearchResult(
                entity_type=entity_type,
                total=0,
                hits=[],
            )

        # Build tsquery based on syntax
        ts_config = config.config
        query_to_use = expanded_query if self.enable_synonyms else request.query
        ts_query = self._build_tsquery(query_to_use, request.syntax, ts_config)

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

        # Apply intent-based adjustments
        limit = request.limit
        if intent and intent.is_high_confidence:
            adjustments = intent.suggested_adjustments
            if adjustments.get("limit_results"):
                limit = min(limit, adjustments["limit_results"])
            elif adjustments.get("increase_limit"):
                limit = min(limit * 2, config.max_results)

        # Main query
        stmt = (
            select(  # type: ignore
                model_class,
                rank_expr.label("rank"),
            )
            .where(search_vector.op("@@")(ts_query))
            .where(rank_expr >= request.min_rank)
            .order_by(rank_expr.desc())
            .offset(request.offset)
            .limit(limit)
        )

        # Execute search
        result = await self.session.execute(stmt)
        rows = result.all()

        # If no FTS results and fuzzy is enabled, try fuzzy search
        if not rows and self.enable_fuzzy_fallback and config.fuzzy_fields:
            rows = await self._fuzzy_search(model_class, config, request)

        # Get total count
        count_stmt = (
            select(func.count())
            .select_from(model_class)  # type: ignore
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
            if config.title_field:
                title = getattr(entity, config.title_field, None)

            # Get snippet with highlighting
            snippet = None
            if request.highlight and config.snippet_field:
                snippet = await self._get_highlighted_snippet(
                    entity,
                    request.query,
                    config.snippet_field,
                    ts_config,
                    request.highlight_tag,
                )
            elif config.snippet_field:
                snippet_text = getattr(entity, config.snippet_field, None)
                if snippet_text:
                    snippet = (
                        snippet_text[:200] + "..."
                        if len(snippet_text) > 200
                        else snippet_text
                    )

            # Build entity data
            entity_id = str(getattr(entity, config.id_field, "id"))
            created_at = getattr(entity, "created_at", None)

            # Get entity data as dict
            if hasattr(entity, "model_dump"):
                data = entity.model_dump()
            elif hasattr(entity, "__dict__"):
                data = {
                    k: v for k, v in entity.__dict__.items() if not k.startswith("_")
                }
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
        if request.include_facets and config.facet_fields:
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
        config: EntitySearchConfig,
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
        fuzzy_fields = config.fuzzy_fields
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
        max_sim = (
            similarities[0] if len(similarities) == 1 else func.greatest(*similarities)
        )

        stmt = (
            select(model_class, max_sim.label("rank"))
            .where(or_(*conditions))
            .order_by(max_sim.desc())
            .offset(request.offset)
            .limit(request.limit)
        )

        try:
            result = await self.session.execute(stmt)
            return result.all()  # type: ignore
        except Exception as e:
            logger.warning("Fuzzy search failed: %s", e)
            return []

    async def _get_facets(
        self,
        model_class: Any,
        config: EntitySearchConfig,
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
        facet_fields = config.facet_fields

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
                    FacetValue(
                        value=str(row[0]) if row[0] is not None else "null",
                        count=row[1],
                    )
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
                logger.warning("Facet query failed for %s: %s", field_name, e)

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
            config = self._config.entity_registry.get(entity_type)
            if not config:
                continue

            model_class = self._import_model(config.model_path)
            fuzzy_fields = config.fuzzy_fields

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
                    logger.debug("Did you mean query failed: %s", e)

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
            entity_types = self._config.entity_registry.list_entities()

        for entity_type in entity_types:
            config = self._config.entity_registry.get(entity_type)
            if not config:
                continue

            model_class = self._import_model(config.model_path)

            if not hasattr(model_class, "search_vector"):
                continue

            # Build prefix query
            ts_config = config.config
            # Add :* for prefix matching
            prefix_query = request.prefix + ":*"

            try:
                ts_query = func.to_tsquery(ts_config, prefix_query)
            except Exception:
                # Fall back to plain text query if prefix query fails
                ts_query = func.plainto_tsquery(ts_config, request.prefix)

            # Get matching titles
            title_field = config.title_field
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
                logger.warning("Suggestion query failed for %s: %s", entity_type, e)
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
        if syntax == SearchSyntax.PHRASE:
            return func.phraseto_tsquery(config, query)
        # PLAIN
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
            return snippet if snippet else text_value[:200]  # type: ignore
        except Exception as e:
            logger.debug("Highlighting failed: %s", e)
            return text_value[:200] + "..." if len(text_value) > 200 else text_value  # type: ignore

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

    def _import_model(self, model_path: str) -> Any:
        """Dynamically import a model class.

        Args:
            model_path: Full module path to model.

        Returns:
            Model class.
        """
        parts = model_path.rsplit(".", 1)
        module_path, class_name = parts

        module = importlib.import_module(module_path)
        return getattr(module, class_name)

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

    # ──────────────────────────────────────────────────────────────
    # Performance Profiling Methods
    # ──────────────────────────────────────────────────────────────

    async def get_slow_queries(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get slow query information.

        Args:
            days: Number of days to analyze.
            limit: Maximum queries to return.

        Returns:
            List of slow query records.
        """
        if not self._profiler:
            return []

        return await self._profiler.get_slow_queries(days=days, limit=limit)

    async def get_performance_stats(
        self,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Get query performance statistics.

        Args:
            days: Number of days to analyze.

        Returns:
            List of performance stats.
        """
        if not self._profiler:
            return []

        stats = await self._profiler.get_performance_stats(days=days)
        return [
            {
                "query_type": s.query_type,
                "total_queries": s.total_queries,
                "avg_time_ms": s.avg_time_ms,
                "p50_time_ms": s.p50_time_ms,
                "p95_time_ms": s.p95_time_ms,
                "p99_time_ms": s.p99_time_ms,
                "slow_query_rate": s.slow_query_rate,
            }
            for s in stats
        ]


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
