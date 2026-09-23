"""add order_placed and order_picked_up notification types

Revision ID: 20260926_37
Revises: 20260925_36
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260926_37"
down_revision: Union[str, Sequence[str], None] = "20260925_36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "order_placed",
    "order_picked_up",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added labels are
    # left in place on downgrade — same precedent as every other
    # enum-value-addition migration in this project.
    pass
