"""add rider notification types

Revision ID: 20260915_24
Revises: 20260915_23
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260915_24"
down_revision: Union[str, Sequence[str], None] = "20260915_23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "new_delivery",
    "delivery_cancelled",
    "delivery_updated",
    "payment_update",
    "earning_update",
    "account_approved",
    "account_suspended",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added labels are left
    # in place on downgrade — same precedent as every other enum-value-
    # addition migration in this project.
    pass
