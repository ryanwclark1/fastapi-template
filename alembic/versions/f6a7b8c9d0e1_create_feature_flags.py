"""create_feature_flags

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2025-12-01 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create feature flags tables."""
    # Create feature_flags table
    op.create_table(
        "feature_flags",
        # Primary key (UUID v7 for time-ordering)
        sa.Column("id", sa.Uuid(), nullable=False),
        # Flag identification
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Flag state
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="disabled",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("percentage", sa.Integer(), nullable=False, server_default="0"),
        # Targeting and metadata (JSONB)
        sa.Column("targeting_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Time-based activation
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature_flags")),
        sa.UniqueConstraint("key", name=op.f("uq_feature_flags_key")),
    )

    # Indexes for feature_flags
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"], unique=True)
    op.create_index("ix_feature_flags_status", "feature_flags", ["status"], unique=False)
    op.create_index("ix_feature_flags_enabled", "feature_flags", ["enabled"], unique=False)

    # Create flag_overrides table
    op.create_table(
        "flag_overrides",
        # Primary key
        sa.Column("id", sa.Uuid(), nullable=False),
        # Override identification
        sa.Column("flag_key", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
        # Override value
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flag_overrides")),
    )

    # Indexes for flag_overrides
    op.create_index("ix_flag_overrides_flag_key", "flag_overrides", ["flag_key"], unique=False)
    op.create_index(
        "ix_flag_overrides_lookup",
        "flag_overrides",
        ["flag_key", "entity_type", "entity_id"],
        unique=True,
    )
    op.create_index(
        "ix_flag_overrides_entity",
        "flag_overrides",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop feature flags tables."""
    # Drop flag_overrides indexes and table
    op.drop_index("ix_flag_overrides_entity", table_name="flag_overrides")
    op.drop_index("ix_flag_overrides_lookup", table_name="flag_overrides")
    op.drop_index("ix_flag_overrides_flag_key", table_name="flag_overrides")
    op.drop_table("flag_overrides")

    # Drop feature_flags indexes and table
    op.drop_index("ix_feature_flags_enabled", table_name="feature_flags")
    op.drop_index("ix_feature_flags_status", table_name="feature_flags")
    op.drop_index("ix_feature_flags_key", table_name="feature_flags")
    op.drop_table("feature_flags")
