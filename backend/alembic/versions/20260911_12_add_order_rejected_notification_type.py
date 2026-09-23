"""add order_rejected notification type

Revision ID: 20260911_12
Revises: 20260910_11
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260911_12"
down_revision: Union[str, Sequence[str], None] = "20260910_11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'order_rejected'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added label is left in
    # place on downgrade (harmless once the app code that used it is reverted).
    pass
