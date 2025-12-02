"""add_fts_to_posts_and_users

Revision ID: g7h8i9j0k1l2
Revises: 0fae80f19092
Create Date: 2025-12-02 12:00:00.000000

Adds full-text search capabilities to posts and users tables:
- search_vector TSVECTOR column
- GIN indexes for fast FTS queries
- Triggers for automatic search vector updates
- Trigram indexes for fuzzy search
- Extensions: pg_trgm for fuzzy search

Posts search includes: title (A), content (B), slug (C)
Users search includes: email (A), username (A), full_name (B)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: str | None = "0fae80f19092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add full-text search to posts and users tables."""
    # =========================================================================
    # Enable pg_trgm extension for fuzzy search
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # =========================================================================
    # POSTS TABLE - Full-text search
    # =========================================================================

    # Add search_vector column to posts
    op.add_column("posts", sa.Column("search_vector", TSVECTOR(), nullable=True))

    # Create GIN index for fast full-text search on posts
    op.create_index(
        "ix_posts_search_vector",
        "posts",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    # Create trigram index on title for fuzzy search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_posts_title_trgm
        ON posts USING gin (title gin_trgm_ops);
    """)

    # Create trigger function for posts search vector
    op.execute("""
        CREATE OR REPLACE FUNCTION posts_search_vector_update() RETURNS trigger AS $$
        BEGIN
            -- Only update if searchable fields changed (for UPDATE) or on INSERT
            IF TG_OP = 'INSERT' OR
               OLD.title IS DISTINCT FROM NEW.title OR
               OLD.content IS DISTINCT FROM NEW.content OR
               OLD.slug IS DISTINCT FROM NEW.slug THEN
                NEW.search_vector :=
                    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.content, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.slug, '')), 'C');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger for posts
    op.execute("""
        DROP TRIGGER IF EXISTS posts_search_update ON posts;
        CREATE TRIGGER posts_search_update
            BEFORE INSERT OR UPDATE ON posts
            FOR EACH ROW
            EXECUTE FUNCTION posts_search_vector_update();
    """)

    # Backfill existing posts with search vectors
    op.execute("""
        UPDATE posts SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(content, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(slug, '')), 'C');
    """)

    # =========================================================================
    # USERS TABLE - Full-text search
    # =========================================================================

    # Add search_vector column to users
    op.add_column("users", sa.Column("search_vector", TSVECTOR(), nullable=True))

    # Create GIN index for fast full-text search on users
    op.create_index(
        "ix_users_search_vector",
        "users",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    # Create trigram indexes for fuzzy search on username and full_name
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_username_trgm
        ON users USING gin (username gin_trgm_ops);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_full_name_trgm
        ON users USING gin (full_name gin_trgm_ops);
    """)

    # Create trigger function for users search vector
    op.execute("""
        CREATE OR REPLACE FUNCTION users_search_vector_update() RETURNS trigger AS $$
        BEGIN
            -- Only update if searchable fields changed (for UPDATE) or on INSERT
            IF TG_OP = 'INSERT' OR
               OLD.email IS DISTINCT FROM NEW.email OR
               OLD.username IS DISTINCT FROM NEW.username OR
               OLD.full_name IS DISTINCT FROM NEW.full_name THEN
                NEW.search_vector :=
                    setweight(to_tsvector('simple', coalesce(NEW.email, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(NEW.username, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.full_name, '')), 'B');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger for users
    op.execute("""
        DROP TRIGGER IF EXISTS users_search_update ON users;
        CREATE TRIGGER users_search_update
            BEFORE INSERT OR UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION users_search_vector_update();
    """)

    # Backfill existing users with search vectors
    op.execute("""
        UPDATE users SET search_vector =
            setweight(to_tsvector('simple', coalesce(email, '')), 'A') ||
            setweight(to_tsvector('simple', coalesce(username, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(full_name, '')), 'B');
    """)

    # =========================================================================
    # SEARCH_QUERIES TABLE - For analytics
    # =========================================================================
    op.create_table(
        "search_queries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query_text", sa.String(500), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("normalized_query", sa.String(500), nullable=True),
        sa.Column("entity_types", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("results_count", sa.Integer(), default=0, nullable=False),
        sa.Column("took_ms", sa.Integer(), default=0, nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("clicked_result", sa.Boolean(), default=False, nullable=False),
        sa.Column("clicked_position", sa.Integer(), nullable=True),
        sa.Column("clicked_entity_id", sa.String(255), nullable=True),
        sa.Column("search_syntax", sa.String(50), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_queries_query_text", "search_queries", ["query_text"])
    op.create_index("ix_search_queries_query_hash", "search_queries", ["query_hash"])
    op.create_index("ix_search_queries_user_id", "search_queries", ["user_id"])
    op.create_index("ix_search_queries_created_at", "search_queries", ["created_at"])

    # =========================================================================
    # SEARCH_SUGGESTION_LOGS TABLE - For tracking suggestions
    # =========================================================================
    op.create_table(
        "search_suggestion_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prefix", sa.String(100), nullable=False),
        sa.Column("suggested_text", sa.String(500), nullable=False),
        sa.Column("was_selected", sa.Boolean(), default=False, nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_suggestion_logs_prefix", "search_suggestion_logs", ["prefix"])


def downgrade() -> None:
    """Remove full-text search from posts and users tables."""
    # =========================================================================
    # Remove search analytics tables
    # =========================================================================
    op.drop_table("search_suggestion_logs")
    op.drop_table("search_queries")

    # =========================================================================
    # USERS TABLE - Remove FTS
    # =========================================================================

    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS users_search_update ON users;")

    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS users_search_vector_update();")

    # Drop trigram indexes
    op.execute("DROP INDEX IF EXISTS ix_users_username_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_users_full_name_trgm;")

    # Drop GIN index
    op.drop_index("ix_users_search_vector", table_name="users")

    # Drop column
    op.drop_column("users", "search_vector")

    # =========================================================================
    # POSTS TABLE - Remove FTS
    # =========================================================================

    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS posts_search_update ON posts;")

    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS posts_search_vector_update();")

    # Drop trigram index
    op.execute("DROP INDEX IF EXISTS ix_posts_title_trgm;")

    # Drop GIN index
    op.drop_index("ix_posts_search_vector", table_name="posts")

    # Drop column
    op.drop_column("posts", "search_vector")

    # Note: We don't drop pg_trgm extension as other tables might use it
