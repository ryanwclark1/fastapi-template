"""Post-process Alembic migrations to inject PostgreSQL extension and index code.

This script is called after migration generation to automatically inject:
- FTSMigrationHelper calls for models with __search_fields__ configuration
- Trigram indexes for models with __trigram_fields__ configuration
- PostgreSQL extensions (pg_trgm, unaccent, ltree, btree_gist) as needed
- GiST indexes for ltree columns (hierarchical models)
- GiST indexes for range type columns

Detection is based on model attributes:
- __search_fields__: Full-text search fields
- __trigram_fields__: Fuzzy search fields
- __path_column__: Hierarchical data (ltree)
- Range columns: Detected via column type inspection
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from example_service.core import models  # noqa: F401 - needed to load models
from example_service.core.database.base import Base


def collect_fts_models() -> list[dict[str, Any]]:
    """Collect all models with FTS configuration."""
    fts_models = []

    for mapper in Base.registry.mappers:
        model_class = mapper.class_
        if hasattr(model_class, "__search_fields__"):
            table_name = mapper.persist_selectable.name  # type: ignore[attr-defined]
            fts_models.append(
                {
                    "table_name": table_name,
                    "search_fields": model_class.__search_fields__,
                    "config": getattr(model_class, "__search_config__", "english"),
                    "weights": getattr(model_class, "__search_weights__", None),
                }
            )

    return fts_models


def collect_trigram_models() -> list[dict[str, Any]]:
    """Collect all models with trigram configuration."""
    trigram_models = []

    for mapper in Base.registry.mappers:
        model_class = mapper.class_
        if hasattr(model_class, "__trigram_fields__") and model_class.__trigram_fields__:
            table_name = mapper.persist_selectable.name  # type: ignore[attr-defined]
            trigram_models.append(
                {
                    "table_name": table_name,
                    "trigram_fields": model_class.__trigram_fields__,
                }
            )

    return trigram_models


def collect_hierarchical_models() -> list[dict[str, Any]]:
    """Collect all models with hierarchical (ltree) configuration.

    Detects models that:
    - Have __path_column__ attribute (HierarchicalMixin)
    - Use LtreeType columns directly

    Returns:
        List of dicts with table_name and path_column for each hierarchical model
    """
    hierarchical_models = []

    for mapper in Base.registry.mappers:
        model_class = mapper.class_
        table_name = mapper.persist_selectable.name  # type: ignore[attr-defined]

        # Check for HierarchicalMixin (__path_column__ attribute)
        if hasattr(model_class, "__path_column__"):
            path_column = model_class.__path_column__
            hierarchical_models.append(
                {
                    "table_name": table_name,
                    "path_column": path_column,
                }
            )
            continue

        # Also detect LtreeType columns directly (without mixin)
        table = mapper.persist_selectable
        for column in table.columns:
            col_type = str(column.type).upper()
            if col_type == "LTREE" or "LtreeType" in str(type(column.type)):
                hierarchical_models.append(
                    {
                        "table_name": table_name,
                        "path_column": column.name,
                    }
                )
                break  # One entry per table is enough

    return hierarchical_models


def collect_range_models() -> list[dict[str, Any]]:
    """Collect all models with PostgreSQL range type columns.

    Detects columns using:
    - DATERANGE, TSTZRANGE, TSRANGE
    - INT4RANGE, INT8RANGE
    - NUMRANGE

    Returns:
        List of dicts with table_name and range_columns for each model
    """
    range_models = []
    range_type_patterns = (
        "DATERANGE",
        "TSTZRANGE",
        "TSRANGE",
        "INT4RANGE",
        "INT8RANGE",
        "NUMRANGE",
    )

    for mapper in Base.registry.mappers:
        table = mapper.persist_selectable
        table_name = table.name  # type: ignore[attr-defined]
        range_columns = []

        for column in table.columns:
            col_type = str(column.type).upper()
            if any(rt in col_type for rt in range_type_patterns):
                range_columns.append(column.name)

        if range_columns:
            range_models.append(
                {
                    "table_name": table_name,
                    "range_columns": range_columns,
                }
            )

    return range_models


def collect_required_extensions(
    fts_models: list[dict[str, Any]],
    trigram_models: list[dict[str, Any]],
    hierarchical_models: list[dict[str, Any]] | None = None,
    range_models: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Determine which PostgreSQL extensions are needed.

    Args:
        fts_models: List of FTS model configurations
        trigram_models: List of trigram model configurations
        hierarchical_models: List of hierarchical (ltree) model configurations
        range_models: List of range type model configurations

    Returns:
        List of extension names needed (in recommended creation order)
    """
    extensions = []

    # If we have FTS or trigram models, we need both core search extensions
    if fts_models or trigram_models:
        # pg_trgm for fuzzy/similarity search
        extensions.append("pg_trgm")
        # unaccent for accent-insensitive search (always useful for FTS)
        extensions.append("unaccent")

    # If we have hierarchical models, we need ltree
    if hierarchical_models:
        extensions.append("ltree")

    # If we have range models, we likely need btree_gist for exclusion constraints
    # btree_gist allows using = operator with GiST indexes (needed for exclusion
    # constraints that combine range types with scalar types like room_id = ...)
    if range_models:
        extensions.append("btree_gist")

    return extensions


def generate_fts_upgrade_code(
    fts_models: list[dict[str, Any]], initial_migration: bool = False
) -> str:
    """Generate FTS setup code for upgrade function.

    Args:
        fts_models: List of FTS model configurations
        initial_migration: If True, generates code for migrations where columns already exist
    """
    if not fts_models:
        return ""

    lines = [
        "",
        "    # Add Full-Text Search triggers for automatic search_vector updates",
    ]

    for model in fts_models:
        table_name = model["table_name"]
        search_fields = model["search_fields"]
        config = model["config"]
        weights = model["weights"]

        lines.append(f"    # {table_name.capitalize()} FTS")

        if initial_migration:
            # For initial migrations, columns already exist - only add triggers/indexes
            helper_var = f"helper_{table_name}"
            lines.append(f"    {helper_var} = FTSMigrationHelper(")
            lines.append(f'        table_name="{table_name}",')
            lines.append(f"        search_fields={search_fields!r},")
            if weights:
                lines.append(f"        weights={weights!r},")
            lines.append(f'        config="{config}",')
            lines.append("    )")
            lines.append("")
            lines.append("    # Create GIN index (column already exists from table creation)")
            lines.append("    op.create_index(")
            lines.append(f"        {helper_var}.index_name,")
            lines.append(f'        "{table_name}",')
            lines.append(f"        [{helper_var}.column_name],")
            lines.append("        unique=False,")
            lines.append('        postgresql_using="gin",')
            lines.append("    )")
            lines.append("")
            lines.append("    # Create trigger function and trigger")
            lines.append(f"    op.execute({helper_var}.get_trigger_function_sql())")
            lines.append(f"    op.execute({helper_var}.get_trigger_sql())")
            lines.append("")
            lines.append("    # Backfill existing data (usually empty for initial migration)")
            lines.append(f"    op.execute({helper_var}.get_backfill_sql())")
        else:
            # For subsequent migrations, use full add_fts() which creates columns
            lines.append("    FTSMigrationHelper(")
            lines.append(f'        table_name="{table_name}",')
            lines.append(f"        search_fields={search_fields!r},")
            if weights:
                lines.append(f"        weights={weights!r},")
            lines.append(f'        config="{config}",')
            lines.append("    ).add_fts(op)")

        lines.append("")

    return "\n".join(lines)


def generate_fts_downgrade_code(fts_models: list[dict[str, Any]]) -> str:
    """Generate FTS removal code for downgrade function."""
    if not fts_models:
        return ""

    lines = [
        "",
        "    # Remove Full-Text Search triggers",
    ]

    # Reverse order for downgrade
    for model in reversed(fts_models):
        table_name = model["table_name"]
        search_fields = model["search_fields"]
        config = model["config"]
        weights = model["weights"]

        lines.append("    FTSMigrationHelper(")
        lines.append(f'        table_name="{table_name}",')
        lines.append(f"        search_fields={search_fields!r},")

        if weights:
            lines.append(f"        weights={weights!r},")

        lines.append(f'        config="{config}",')
        lines.append("    ).remove_fts(op)")
        lines.append("")

    return "\n".join(lines)


def generate_extension_code(extensions: list[str]) -> str:
    """Generate PostgreSQL extension creation code.

    Args:
        extensions: List of extension names to create

    Returns:
        Python code string for creating extensions
    """
    if not extensions:
        return ""

    lines = [
        "",
        "    # Create required PostgreSQL extensions",
    ]

    for ext in extensions:
        lines.append(f'    op.execute("CREATE EXTENSION IF NOT EXISTS {ext};")')

    lines.append("")
    return "\n".join(lines)


def generate_trigram_upgrade_code(trigram_models: list[dict[str, Any]]) -> str:
    """Generate trigram index creation code.

    Args:
        trigram_models: List of trigram model configurations

    Returns:
        Python code string for creating trigram indexes
    """
    if not trigram_models:
        return ""

    lines = [
        "",
        "    # Create trigram indexes for fuzzy search",
    ]

    for model in trigram_models:
        table_name = model["table_name"]
        trigram_fields = model["trigram_fields"]

        for field in trigram_fields:
            index_name = f"ix_{table_name}_{field}_trgm"
            lines.append(f"    # {table_name}.{field} trigram index")
            lines.append("    op.create_index(")
            lines.append(f'        "{index_name}",')
            lines.append(f'        "{table_name}",')
            lines.append(f'        ["{field}"],')
            lines.append("        unique=False,")
            lines.append('        postgresql_using="gist",')
            lines.append("        postgresql_ops={")
            lines.append(f'            "{field}": "gist_trgm_ops"')
            lines.append("        },")
            lines.append("    )")
            lines.append("")

    return "\n".join(lines)


def generate_trigram_downgrade_code(trigram_models: list[dict[str, Any]]) -> str:
    """Generate trigram index removal code.

    Args:
        trigram_models: List of trigram model configurations

    Returns:
        Python code string for dropping trigram indexes
    """
    if not trigram_models:
        return ""

    lines = [
        "",
        "    # Remove trigram indexes",
    ]

    # Reverse order for downgrade
    for model in reversed(trigram_models):
        table_name = model["table_name"]
        trigram_fields = model["trigram_fields"]

        for field in reversed(trigram_fields):
            index_name = f"ix_{table_name}_{field}_trgm"
            lines.append(f'    op.drop_index("{index_name}", table_name="{table_name}")')

    lines.append("")
    return "\n".join(lines)


def generate_hierarchical_upgrade_code(hierarchical_models: list[dict[str, Any]]) -> str:
    """Generate GiST index creation code for hierarchical (ltree) columns.

    Creates both GiST indexes (for @>, <@, ~ operators) and optionally
    B-tree indexes (for ORDER BY and exact matches).

    Args:
        hierarchical_models: List of hierarchical model configurations

    Returns:
        Python code string for creating ltree indexes
    """
    if not hierarchical_models:
        return ""

    lines = [
        "",
        "    # Create GiST indexes for hierarchical (ltree) columns",
    ]

    for model in hierarchical_models:
        table_name = model["table_name"]
        path_column = model["path_column"]

        # GiST index for ancestor/descendant queries
        gist_index_name = f"ix_{table_name}_{path_column}_gist"
        lines.append(f"    # {table_name}.{path_column} ltree GiST index")
        lines.append("    op.execute(")
        lines.append(f'        "CREATE INDEX {gist_index_name} ON {table_name} '
                     f'USING GIST ({path_column})"')
        lines.append("    )")
        lines.append("")

    return "\n".join(lines)


def generate_hierarchical_downgrade_code(hierarchical_models: list[dict[str, Any]]) -> str:
    """Generate code to drop hierarchical (ltree) indexes.

    Args:
        hierarchical_models: List of hierarchical model configurations

    Returns:
        Python code string for dropping ltree indexes
    """
    if not hierarchical_models:
        return ""

    lines = [
        "",
        "    # Remove hierarchical (ltree) indexes",
    ]

    # Reverse order for downgrade
    for model in reversed(hierarchical_models):
        table_name = model["table_name"]
        path_column = model["path_column"]

        gist_index_name = f"ix_{table_name}_{path_column}_gist"
        lines.append(f'    op.execute("DROP INDEX IF EXISTS {gist_index_name}")')

    lines.append("")
    return "\n".join(lines)


def generate_range_upgrade_code(range_models: list[dict[str, Any]]) -> str:
    """Generate GiST index creation code for range type columns.

    GiST indexes enable efficient:
    - Containment queries (@>, <@)
    - Overlap queries (&&)
    - Adjacency queries (-|-)

    Args:
        range_models: List of range model configurations

    Returns:
        Python code string for creating range indexes
    """
    if not range_models:
        return ""

    lines = [
        "",
        "    # Create GiST indexes for range type columns",
    ]

    for model in range_models:
        table_name = model["table_name"]
        range_columns = model["range_columns"]

        for column in range_columns:
            index_name = f"ix_{table_name}_{column}_gist"
            lines.append(f"    # {table_name}.{column} range GiST index")
            lines.append("    op.execute(")
            lines.append(f'        "CREATE INDEX {index_name} ON {table_name} '
                         f'USING GIST ({column})"')
            lines.append("    )")
            lines.append("")

    return "\n".join(lines)


def generate_range_downgrade_code(range_models: list[dict[str, Any]]) -> str:
    """Generate code to drop range type indexes.

    Args:
        range_models: List of range model configurations

    Returns:
        Python code string for dropping range indexes
    """
    if not range_models:
        return ""

    lines = [
        "",
        "    # Remove range type indexes",
    ]

    # Reverse order for downgrade
    for model in reversed(range_models):
        table_name = model["table_name"]
        range_columns = model["range_columns"]

        for column in reversed(range_columns):
            index_name = f"ix_{table_name}_{column}_gist"
            lines.append(f'    op.execute("DROP INDEX IF EXISTS {index_name}")')

    lines.append("")
    return "\n".join(lines)


def inject_fts_code(migration_file: Path) -> bool:
    """Inject FTS, trigram, hierarchical, range, and extension code into a migration file.

    Args:
        migration_file: Path to the migration file

    Returns:
        True if code was injected, False otherwise
    """
    # Collect all model configurations
    fts_models = collect_fts_models()
    trigram_models = collect_trigram_models()
    hierarchical_models = collect_hierarchical_models()
    range_models = collect_range_models()

    # Determine required extensions based on all model types
    extensions = collect_required_extensions(
        fts_models, trigram_models, hierarchical_models, range_models
    )

    # Check if there's anything to inject
    has_content = (
        fts_models or trigram_models or hierarchical_models or range_models or extensions
    )
    if not has_content:
        print("No FTS/trigram/hierarchical/range models or extensions found, skipping injection")
        return False

    # Report what was found
    if fts_models:
        print(f"\nFound {len(fts_models)} FTS-enabled models:")
        for model in fts_models:
            print(f"  - {model['table_name']}: {model['search_fields']}")

    if trigram_models:
        print(f"\nFound {len(trigram_models)} trigram-enabled models:")
        for model in trigram_models:
            print(f"  - {model['table_name']}: {model['trigram_fields']}")

    if hierarchical_models:
        print(f"\nFound {len(hierarchical_models)} hierarchical (ltree) models:")
        for model in hierarchical_models:
            print(f"  - {model['table_name']}.{model['path_column']}")

    if range_models:
        print(f"\nFound {len(range_models)} models with range columns:")
        for model in range_models:
            print(f"  - {model['table_name']}: {model['range_columns']}")

    if extensions:
        print(f"\nRequired extensions: {', '.join(extensions)}")

    # Read migration file
    content = migration_file.read_text()

    # Detect initial migration (creates many tables at once)
    # Check if this migration creates tables for FTS models (indicates initial migration)
    is_initial = bool(
        fts_models
        and all(
            f'"{model["table_name"]}",' in content and "op.create_table" in content
            for model in fts_models
        )
    )

    if is_initial:
        print("\nDetected initial migration (columns already created by autogenerate)")
    elif fts_models:
        print("\nDetected subsequent migration (will create columns)")

    # Generate code for each category
    extension_code = generate_extension_code(extensions)
    fts_upgrade_code = (
        generate_fts_upgrade_code(fts_models, initial_migration=is_initial) if fts_models else ""
    )
    fts_downgrade_code = generate_fts_downgrade_code(fts_models) if fts_models else ""
    trigram_upgrade_code = generate_trigram_upgrade_code(trigram_models)
    trigram_downgrade_code = generate_trigram_downgrade_code(trigram_models)
    hierarchical_upgrade_code = generate_hierarchical_upgrade_code(hierarchical_models)
    hierarchical_downgrade_code = generate_hierarchical_downgrade_code(hierarchical_models)
    range_upgrade_code = generate_range_upgrade_code(range_models)
    range_downgrade_code = generate_range_downgrade_code(range_models)

    # Check if code already injected (any of our markers present)
    already_injected_markers = [
        "FTSMigrationHelper",
        "gist_trgm_ops",
        "CREATE EXTENSION",
        "ltree GiST index",
        "range GiST index",
    ]
    if any(marker in content for marker in already_injected_markers):
        print("\nExtension/index code already present in migration, skipping")
        return False

    # Add import if FTS models exist
    if (
        fts_models
        and "from example_service.core.database.search.utils import FTSMigrationHelper"
        not in content
    ):
        # Find the imports section and add our import
        import_pattern = r"(from alembic import op\n)"
        content = re.sub(
            import_pattern,
            r"\1from example_service.core.database.search.utils import FTSMigrationHelper\n",
            content,
        )

    # Build combined upgrade code
    # Order: extensions first, then FTS, trigram, hierarchical, range
    combined_upgrade_code = (
        extension_code
        + fts_upgrade_code
        + trigram_upgrade_code
        + hierarchical_upgrade_code
        + range_upgrade_code
    )

    # Build combined downgrade code (reverse order)
    combined_downgrade_code = (
        range_downgrade_code
        + hierarchical_downgrade_code
        + trigram_downgrade_code
        + fts_downgrade_code
    )

    # Inject upgrade code before the closing of upgrade()
    # Find the end of the upgrade function (before next function definition)
    upgrade_pattern = (
        r"(def upgrade\(\) -> None:.*?)(    # ### end Alembic commands ###|def downgrade)"
    )
    match = re.search(upgrade_pattern, content, re.DOTALL)
    if match and combined_upgrade_code:
        content = (
            content[: match.start(2)] + combined_upgrade_code + "\n" + content[match.start(2) :]
        )

    # Inject downgrade code at the start of downgrade()
    downgrade_pattern = r'(def downgrade\(\) -> None:\s*""".*?"""\s*# ### commands auto generated by Alembic[^\n]*\n)'
    match = re.search(downgrade_pattern, content, re.DOTALL)
    if match and combined_downgrade_code:
        content = content[: match.end()] + combined_downgrade_code + "\n" + content[match.end() :]

    # Write back
    migration_file.write_text(content)

    # Report what was injected
    injected_items = []
    if extensions:
        injected_items.append(f"{len(extensions)} extensions ({', '.join(extensions)})")
    if fts_models:
        injected_items.append(f"{len(fts_models)} FTS triggers")
    if trigram_models:
        injected_items.append(f"{len(trigram_models)} trigram indexes")
    if hierarchical_models:
        injected_items.append(f"{len(hierarchical_models)} ltree GiST indexes")
    if range_models:
        total_range_cols = sum(len(m["range_columns"]) for m in range_models)
        injected_items.append(f"{total_range_cols} range GiST indexes")

    print(f"\n✓ Injected {', '.join(injected_items)} into {migration_file.name}")
    return True


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python inject_fts.py <migration_file>")
        return 1

    migration_file = Path(sys.argv[1])
    if not migration_file.exists():
        print(f"Error: Migration file not found: {migration_file}")
        return 1

    try:
        inject_fts_code(migration_file)
        return 0  # Always succeed
    except Exception as e:
        print(f"Error injecting FTS code: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
