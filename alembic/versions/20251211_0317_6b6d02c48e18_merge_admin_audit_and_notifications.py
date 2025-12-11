"""merge admin audit and notifications

Revision ID: 6b6d02c48e18
Revises: add_admin_audit_table, ba51709f4161
Create Date: 2025-12-11 03:17:05.021405+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6b6d02c48e18'
down_revision: str | None = ('add_admin_audit_table', 'ba51709f4161')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    pass


def downgrade() -> None:
    """Downgrade database schema."""
    pass
