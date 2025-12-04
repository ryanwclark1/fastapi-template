# Full-Text Search Setup Guide

## ✅ Current Infrastructure

Your database is now fully equipped for advanced full-text search:

### PostgreSQL Extensions (Auto-installed)

1. **`pg_trgm`** - Trigram similarity matching
   - Enables fuzzy search: "cafe" matches "café"
   - Used for: Typo tolerance, similarity ranking
   - Automatic via `__trigram_fields__` in models

2. **`unaccent`** - Accent removal
   - Enables accent-insensitive search: "café" = "cafe"
   - Available for custom text search configurations
   - Test: `SELECT unaccent('café')` → "cafe"

### Automatic Features

All of these are **automatically detected and injected** by `alembic/inject_fts.py`:

- ✅ FTS triggers (auto-updates search_vector on INSERT/UPDATE)
- ✅ GIN indexes (fast full-text search)
- ✅ GIST indexes (fuzzy/trigram search)
- ✅ Required extensions (pg_trgm, unaccent)

## 🚀 Adding FTS to New Models

### 1. Basic Full-Text Search

```python
from typing import ClassVar
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

class Article(Base):
    __tablename__ = "articles"

    # Enable FTS on these fields
    __search_fields__: ClassVar[list[str]] = ["title", "content"]
    __search_config__: ClassVar[str] = "english"  # Optional, defaults to "english"

    # Optionally specify field weights (A = highest, D = lowest)
    __search_weights__: ClassVar[dict[str, str]] = {
        "title": "A",    # Title matches ranked highest
        "content": "B",  # Content matches ranked lower
    }

    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text())
    # search_vector column will be auto-created by Alembic
```

Then run:
```bash
alembic revision --autogenerate -m "add_fts_to_articles"
python alembic/inject_fts.py alembic/versions/<new_file>.py
alembic upgrade head
```

**What gets auto-generated:**
- `search_vector` TSVECTOR column
- GIN index on `search_vector`
- Trigger function to auto-update `search_vector`
- Trigger on INSERT/UPDATE
- Backfill of existing data

### 2. Adding Fuzzy Search (Trigram)

```python
class Product(Base):
    __tablename__ = "products"

    # Regular FTS
    __search_fields__: ClassVar[list[str]] = ["name", "description"]

    # Add fuzzy matching on name for typo tolerance
    __trigram_fields__: ClassVar[list[str]] = ["name"]

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text())
```

**What gets auto-generated:**
- All FTS infrastructure (as above)
- GIST index with `gist_trgm_ops` on `name`
- Enables similarity queries like `similarity(name, 'serch query')`

### 3. Using Accent-Insensitive Search

If you need accent-insensitive FTS, create a custom text search configuration:

```python
# In your migration file (after running inject_fts.py), manually add:
from example_service.core.database.search.utils import UnaccentMigrationHelper

def upgrade() -> None:
    # ... auto-generated code ...

    # Add custom unaccent configuration
    UnaccentMigrationHelper(
        config_name="french_unaccent",  # Custom config name
        base_config="french",           # Base language
    ).add_unaccent_config(op)

    # Now use this config in your FTS
    # (Update your model to use __search_config__ = "french_unaccent")
```

Then update your model:
```python
class FrenchContent(Base):
    __tablename__ = "french_content"
    __search_fields__: ClassVar[list[str]] = ["title", "body"]
    __search_config__: ClassVar[str] = "french_unaccent"  # Use custom config
```

## 🔍 Querying Full-Text Search

### Basic Search Query

```python
from sqlalchemy import func, select

# Simple text search
stmt = select(Article).where(
    Article.search_vector.op('@@')(func.to_tsquery('english', 'python & database'))
)

# With ranking
stmt = select(Article).where(
    Article.search_vector.op('@@')(func.to_tsquery('english', 'python'))
).order_by(
    func.ts_rank(Article.search_vector, func.to_tsquery('english', 'python')).desc()
)
```

### Fuzzy Search Query

```python
from sqlalchemy import func

# Find similar names (typo-tolerant)
stmt = select(Product).where(
    func.similarity(Product.name, 'serch query') > 0.3
).order_by(
    func.similarity(Product.name, 'serch query').desc()
)
```

### Using Built-in Search Filters

The codebase includes sophisticated search filters:

```python
from example_service.core.database.search.filters import FullTextSearchFilter

# Use the built-in search system
filter = FullTextSearchFilter(
    field=Article.search_vector,
    query="python programming",
    config="english"
)
stmt = select(Article).where(filter.apply())
```

## 📊 Search Infrastructure Summary

| Feature | Auto-Detected | Manual Setup |
|---------|--------------|--------------|
| Basic FTS | ✅ `__search_fields__` | - |
| Field weights | ✅ `__search_weights__` | - |
| Fuzzy search | ✅ `__trigram_fields__` | - |
| Extensions | ✅ Automatic | - |
| GIN indexes | ✅ Automatic | - |
| GIST indexes | ✅ Automatic | - |
| Triggers | ✅ Automatic | - |
| Custom configs | - | ⚙️ UnaccentMigrationHelper |

## 🎯 Best Practices

1. **Use weights**: Always specify `__search_weights__` to control ranking
2. **Choose config**: Use "simple" for identifiers (usernames, codes), "english" for prose
3. **Limit trigram fields**: Only add trigram indexes to short string fields (< 100 chars)
4. **Test queries**: Use `EXPLAIN ANALYZE` to verify index usage
5. **Monitor performance**: Trigram indexes can be large - monitor disk usage

## 🛠️ Migration Workflow

```bash
# 1. Add __search_fields__ to your model
# 2. Generate migration
alembic revision --autogenerate -m "add_search_to_articles"

# 3. Fix any import errors (TSVECTOR, StringArray)
# (Or automate with pre-commit hook)

# 4. Inject FTS infrastructure
python alembic/inject_fts.py alembic/versions/<file>.py

# 5. Review the generated code
cat alembic/versions/<file>.py | grep -A 10 "FTSMigrationHelper\|CREATE EXTENSION"

# 6. Apply migration
alembic upgrade head
```

## 📚 Advanced Topics

### Available Text Search Configurations

```sql
-- List available configs
SELECT cfgname FROM pg_ts_config;

-- Test configuration
SELECT to_tsvector('english', 'The quick brown foxes jumped');
SELECT to_tsvector('simple', 'user-123');
```

### Creating Custom Dictionaries

If you need stop words, synonyms, or custom stemming, see:
- `UnaccentMigrationHelper` for accent-insensitive configs
- PostgreSQL docs: [Text Search Configuration](https://www.postgresql.org/docs/current/textsearch-configuration.html)

### Search Query Syntax

Supported operators in `to_tsquery`:
- `&` - AND
- `|` - OR
- `!` - NOT
- `<->` - FOLLOWED BY
- `*` - prefix search

Example: `'python & (web | data) & !legacy'`

## 🐛 Troubleshooting

### Search returns no results

```sql
-- Check if search_vector is populated
SELECT id, search_vector FROM articles LIMIT 5;

-- Manually trigger update if needed
UPDATE articles SET search_vector = search_vector;
```

### Slow queries

```sql
-- Verify index is being used
EXPLAIN ANALYZE
SELECT * FROM articles
WHERE search_vector @@ to_tsquery('english', 'python');

-- Should see "Bitmap Heap Scan" using "ix_articles_search_vector"
```

### Extension missing error

```sql
-- Check installed extensions
SELECT * FROM pg_extension WHERE extname IN ('pg_trgm', 'unaccent');

-- Manually install if needed (should be automatic)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
```

## 🔗 Related Documentation

- [GraphQL Features Guide](./graphql-features.md) - Using FTS in GraphQL queries
- [Search Filters](../../example_service/core/database/search/filters.py) - Built-in filter classes
- [Search Utils](../../example_service/core/database/search/utils.py) - Migration helpers
- [PostgreSQL Full-Text Search](https://www.postgresql.org/docs/current/textsearch.html) - Official docs
