"""all tables

Revision ID: 10527cfd05ed
Revises: 43c3ce68c327
Create Date: 2025-12-10 17:49:05.286356+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '10527cfd05ed'
down_revision: str | None = '43c3ce68c327'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    pass


def downgrade() -> None:
    """Downgrade database schema."""
    pass
