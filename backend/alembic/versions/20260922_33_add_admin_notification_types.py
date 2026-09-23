"""add admin notification types

Revision ID: 20260922_33
Revises: 20260921_32
Create Date: 2026-09-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260922_33"
down_revision: Union[str, Sequence[str], None] = "20260921_32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "new_restaurant_registered",
    "new_rider_registered",
    "document_submitted",
    "order_issue",
    "payment_failure",
    "cod_settlement_due",
    "system_alert",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added labels are
    # left in place on downgrade — same precedent as every other
    # enum-value-addition migration in this project.
    pass
