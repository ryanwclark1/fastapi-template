"""Search management CLI commands.

Commands for managing and monitoring full-text search functionality:
- search rebuild: Rebuild all search vectors
- search stats: Show index sizes and scan counts
- search analyze: Generate search quality report
"""

import sys

import click

from example_service.cli.utils import coro, error, header, info, section, success, warning
from example_service.core.settings import get_database_settings
from example_service.infra.database.session import get_engine


@click.group(name="search")
def search() -> None:
    """Search management commands.

    Commands for managing PostgreSQL full-text search functionality
    including rebuilding indexes, viewing statistics, and analyzing
    search quality.
    """


@search.command()
@click.option(
    "--entity",
    "-e",
    multiple=True,
    help="Entity types to rebuild (default: all)",
)
@click.option(
    "--batch-size",
    default=1000,
    type=int,
    help="Number of records to process per batch",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation prompt",
)
@coro
async def rebuild(entity: tuple[str, ...], batch_size: int, force: bool) -> None:
    """Rebuild search vectors for all searchable entities.

    Re-generates the search_vector column for all records by
    re-running the tsvector generation logic. Useful after:
    - Changing search field weights
    - Adding new searchable fields
    - Fixing corrupted search vectors
    """
    from sqlalchemy import text

    from example_service.features.search.service import SEARCHABLE_ENTITIES

    entities_to_rebuild = list(entity) if entity else list(SEARCHABLE_ENTITIES.keys())

    header("Search Vector Rebuild")
    info(f"Entities to rebuild: {', '.join(entities_to_rebuild)}")
    info(f"Batch size: {batch_size}")

    if not force:
        warning("This will rebuild search vectors for all matching records.")
        if not click.confirm("Continue?"):
            info("Rebuild cancelled")
            return

    engine = get_engine()

    async with engine.begin() as conn:
        for entity_type in entities_to_rebuild:
            if entity_type not in SEARCHABLE_ENTITIES:
                warning(f"Unknown entity type: {entity_type}")
                continue

            config = SEARCHABLE_ENTITIES[entity_type]
            model_path = config["model_path"]

            # Get table name from model path
            parts = model_path.rsplit(".", 1)
            module_path, class_name = parts

            import importlib
            module = importlib.import_module(module_path)
            model_class = getattr(module, class_name)
            table_name = model_class.__tablename__

            section(f"Rebuilding: {entity_type} ({table_name})")

            # Get search fields and config from the entity configuration
            search_fields = config.get("search_fields", [])
            ts_config = config.get("config", "english")

            if not search_fields:
                warning(f"  No search fields configured for {entity_type}")
                continue

            # Build the setweight/to_tsvector SQL
            vector_parts = []
            weights = getattr(model_class, "__search_weights__", {})

            for field in search_fields:
                weight = weights.get(field, "D")
                vector_parts.append(
                    f"setweight(to_tsvector('{ts_config}', COALESCE({field}, '')), '{weight}')"
                )

            vector_sql = " || ".join(vector_parts) if vector_parts else f"to_tsvector('{ts_config}', '')"

            # Count total records
            count_result = await conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            total = count_result.scalar() or 0
            info(f"  Total records: {total}")

            if total == 0:
                info("  No records to rebuild")
                continue

            # Rebuild in batches using OFFSET/LIMIT
            processed = 0
            while processed < total:
                update_sql = f"""
                    UPDATE {table_name}
                    SET search_vector = {vector_sql}
                    WHERE id IN (
                        SELECT id FROM {table_name}
                        ORDER BY id
                        LIMIT {batch_size}
                        OFFSET {processed}
                    )
                """

                result = await conn.execute(text(update_sql))
                batch_updated = result.rowcount
                processed += batch_size

                progress = min(processed, total)
                info(f"  Progress: {progress}/{total} ({progress * 100 // total}%)")

            success(f"  Completed: {entity_type}")

    success("\nSearch vector rebuild complete!")


@search.command()
@coro
async def stats() -> None:
    """Show search index statistics.

    Displays information about:
    - Index sizes for each searchable table
    - Number of indexed documents
    - Index health metrics
    """
    from sqlalchemy import text

    from example_service.features.search.service import SEARCHABLE_ENTITIES

    header("Search Index Statistics")

    engine = get_engine()

    async with engine.begin() as conn:
        # Get overall search-related statistics
        section("Index Overview")

        for entity_type, config in SEARCHABLE_ENTITIES.items():
            model_path = config["model_path"]
            parts = model_path.rsplit(".", 1)
            module_path, class_name = parts

            try:
                import importlib
                module = importlib.import_module(module_path)
                model_class = getattr(module, class_name)
                table_name = model_class.__tablename__

                click.echo(f"\n{entity_type} ({table_name}):")

                # Record count
                count_result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                )
                total = count_result.scalar() or 0
                click.echo(f"  Total records: {total:,}")

                # Records with search vector
                if hasattr(model_class, "search_vector"):
                    vector_count_result = await conn.execute(
                        text(f"SELECT COUNT(*) FROM {table_name} WHERE search_vector IS NOT NULL")
                    )
                    indexed = vector_count_result.scalar() or 0
                    click.echo(f"  Indexed records: {indexed:,}")

                    if total > 0:
                        coverage = (indexed / total) * 100
                        click.echo(f"  Index coverage: {coverage:.1f}%")

                # Get index sizes for this table
                index_size_result = await conn.execute(
                    text(f"""
                        SELECT
                            indexname,
                            pg_size_pretty(pg_relation_size(indexrelid)) as size
                        FROM pg_stat_user_indexes
                        WHERE relname = '{table_name}'
                        AND indexname LIKE '%search%' OR indexname LIKE '%trgm%'
                    """)
                )
                indexes = index_size_result.fetchall()

                if indexes:
                    click.echo("  Search indexes:")
                    for idx_name, idx_size in indexes:
                        click.echo(f"    - {idx_name}: {idx_size}")

            except Exception as e:
                warning(f"  Error getting stats for {entity_type}: {e}")

        # Get general index statistics
        section("\nOverall Search Infrastructure")

        # Check if pg_trgm extension is enabled
        trgm_result = await conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        )
        trgm_enabled = trgm_result.scalar()
        click.echo(f"pg_trgm extension: {'enabled' if trgm_enabled else 'not enabled'}")

        # Check if unaccent extension is enabled
        unaccent_result = await conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'unaccent')")
        )
        unaccent_enabled = unaccent_result.scalar()
        click.echo(f"unaccent extension: {'enabled' if unaccent_enabled else 'not enabled'}")

        # Total GIN index size
        gin_size_result = await conn.execute(
            text("""
                SELECT pg_size_pretty(SUM(pg_relation_size(indexrelid)))
                FROM pg_stat_user_indexes
                WHERE indexdef LIKE '%gin%'
            """)
        )
        gin_size = gin_size_result.scalar() or "0 bytes"
        click.echo(f"Total GIN index size: {gin_size}")

    success("\nStats collection complete!")


@search.command()
@click.option(
    "--days",
    default=30,
    type=int,
    help="Number of days to analyze",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file for report (optional)",
)
@coro
async def analyze(days: int, output: str | None) -> None:
    """Generate a search quality report.

    Analyzes search patterns to provide insights on:
    - Search effectiveness (zero-result rate, CTR)
    - Popular search terms
    - Content gaps (frequently searched but no results)
    - Performance metrics
    - Recommendations for improvement
    """
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.database.search import SearchAnalytics
    from example_service.infra.database.session import async_session_maker

    header("Search Quality Analysis")
    info(f"Analyzing last {days} days of search data...")

    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("SEARCH QUALITY REPORT")
    report_lines.append(f"Generated: {datetime.now().isoformat()}")
    report_lines.append(f"Period: Last {days} days")
    report_lines.append("=" * 60)

    async with async_session_maker() as session:
        analytics = SearchAnalytics(session)

        # Get statistics
        stats = await analytics.get_stats(days=days)

        section("Summary Statistics")
        report_lines.append("\n## Summary Statistics")

        metrics = [
            ("Total searches", f"{stats.total_searches:,}"),
            ("Unique queries", f"{stats.unique_queries:,}"),
            ("Zero-result rate", f"{stats.zero_result_rate:.1%}"),
            ("Avg results per search", f"{stats.avg_results_count:.1f}"),
            ("Avg response time", f"{stats.avg_response_time_ms:.0f}ms"),
            ("Click-through rate", f"{stats.click_through_rate:.1%}"),
        ]

        for label, value in metrics:
            line = f"  {label}: {value}"
            click.echo(line)
            report_lines.append(line)

        # Top queries
        section("\nTop Search Queries")
        report_lines.append("\n## Top Search Queries")

        if stats.top_queries:
            for i, query_data in enumerate(stats.top_queries[:10], 1):
                line = f"  {i}. \"{query_data['query']}\" ({query_data['count']} searches, avg {query_data['avg_results']:.0f} results)"
                click.echo(line)
                report_lines.append(line)
        else:
            info("  No search data available")
            report_lines.append("  No search data available")

        # Zero-result queries
        section("\nContent Gaps (Zero-Result Queries)")
        report_lines.append("\n## Content Gaps (Zero-Result Queries)")

        zero_results = await analytics.get_zero_result_queries(days=days, limit=15)
        if zero_results:
            for query_data in zero_results:
                line = f"  - \"{query_data['query']}\" ({query_data['count']} searches)"
                click.echo(line)
                report_lines.append(line)
        else:
            info("  No zero-result queries found")
            report_lines.append("  No zero-result queries found (excellent!)")

        # Slow queries
        section("\nSlow Queries (>500ms)")
        report_lines.append("\n## Slow Queries (>500ms)")

        slow_queries = await analytics.get_slow_queries(days=days, min_time_ms=500, limit=10)
        if slow_queries:
            for query_data in slow_queries:
                line = f"  - \"{query_data['query']}\" (avg {query_data['avg_time_ms']:.0f}ms, max {query_data['max_time_ms']}ms)"
                click.echo(line)
                report_lines.append(line)
        else:
            info("  No slow queries found")
            report_lines.append("  No slow queries found (excellent!)")

        # Generate insights
        section("\nInsights & Recommendations")
        report_lines.append("\n## Insights & Recommendations")

        insights = await analytics.generate_insights(days=days)
        if insights:
            for insight in insights:
                icon = {"warning": "!", "improvement": "*", "info": "i"}
                marker = icon.get(insight.type, "-")
                line = f"  [{marker}] {insight.title}"
                click.echo(line)
                report_lines.append(line)

                if insight.description:
                    desc_line = f"      {insight.description}"
                    click.echo(desc_line)
                    report_lines.append(desc_line)

                if insight.recommendation:
                    rec_line = f"      -> {insight.recommendation}"
                    click.echo(click.style(rec_line, fg="cyan"))
                    report_lines.append(rec_line)
        else:
            info("  No specific insights generated")
            report_lines.append("  No specific insights generated")

    # Save report to file if requested
    if output:
        report_content = "\n".join(report_lines)
        with open(output, "w") as f:
            f.write(report_content)
        success(f"\nReport saved to: {output}")

    success("\nAnalysis complete!")


@search.command()
@click.argument("query")
@click.option(
    "--entity",
    "-e",
    help="Entity type to test (default: first available)",
)
@click.option(
    "--limit",
    default=5,
    type=int,
    help="Maximum results to show",
)
@coro
async def test(query: str, entity: str | None, limit: int) -> None:
    """Test a search query against the database.

    Useful for debugging search issues and tuning.
    """
    from example_service.features.search.schemas import SearchRequest, SearchSyntax
    from example_service.features.search.service import SearchService, SEARCHABLE_ENTITIES
    from example_service.infra.database.session import async_session_maker

    header(f"Testing Search: \"{query}\"")

    # Determine entity type
    if entity and entity not in SEARCHABLE_ENTITIES:
        error(f"Unknown entity type: {entity}")
        error(f"Available: {', '.join(SEARCHABLE_ENTITIES.keys())}")
        sys.exit(1)

    entity_types = [entity] if entity else None

    async with async_session_maker() as session:
        service = SearchService(session, enable_analytics=False)

        # Test with different syntaxes
        for syntax in [SearchSyntax.WEB, SearchSyntax.PLAIN, SearchSyntax.PHRASE]:
            section(f"\n{syntax.value.upper()} syntax:")

            request = SearchRequest(
                query=query,
                entity_types=entity_types,
                syntax=syntax,
                highlight=True,
                limit=limit,
            )

            response = await service.search(request)

            click.echo(f"  Total hits: {response.total_hits}")
            click.echo(f"  Time: {response.took_ms}ms")

            if response.did_you_mean:
                click.echo(f"  Did you mean: \"{response.did_you_mean.suggested_query}\" ({response.did_you_mean.confidence:.0%} confidence)")

            for result in response.results:
                if result.hits:
                    click.echo(f"\n  {result.entity_type} ({result.total} results):")
                    for hit in result.hits[:limit]:
                        click.echo(f"    - [{hit.rank:.3f}] {hit.title or hit.entity_id}")
                        if hit.snippet:
                            snippet = hit.snippet[:80] + "..." if len(hit.snippet) > 80 else hit.snippet
                            click.echo(f"      {snippet}")

    success("\nTest complete!")


@search.command()
@coro
async def triggers() -> None:
    """Show search trigger status.

    Lists all search-related triggers and their status.
    """
    from sqlalchemy import text

    header("Search Triggers Status")

    engine = get_engine()

    async with engine.begin() as conn:
        # Get all search-related triggers
        result = await conn.execute(
            text("""
                SELECT
                    t.tgname as trigger_name,
                    c.relname as table_name,
                    p.proname as function_name,
                    t.tgenabled as enabled
                FROM pg_trigger t
                JOIN pg_class c ON t.tgrelid = c.oid
                JOIN pg_proc p ON t.tgfoid = p.oid
                WHERE p.proname LIKE '%search%'
                ORDER BY c.relname, t.tgname
            """)
        )
        triggers = result.fetchall()

        if triggers:
            click.echo("\nSearch-related triggers:")
            for tg_name, table_name, func_name, enabled in triggers:
                status = "enabled" if enabled in ("O", "A") else "disabled"
                click.echo(f"  - {tg_name} on {table_name}")
                click.echo(f"    Function: {func_name}")
                click.echo(f"    Status: {status}")
        else:
            warning("No search triggers found")
            info("Run database migrations to create search triggers")

    success("\nTrigger check complete!")
