"""add notification type catalog values (payment/refund/cod/restaurant)

Revision ID: 20261007_51
Revises: 20261007_50
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261007_51"
down_revision: Union[str, Sequence[str], None] = "20261007_50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "payment_success",
    "refund_initiated",
    "refund_completed",
    "cod_pending",
    "cod_collected",
    "restaurant_new_order",
    "restaurant_order_cancelled",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added labels are
    # left in place on downgrade — same precedent as every other
    # enum-value-addition migration in this project.
    pass
