"""add order performance indexes (restaurant_id+created_at, status+created_at)

Revision ID: 20260928_39
Revises: 20260927_38
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260928_39"
down_revision: Union[str, Sequence[str], None] = "20260927_38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_orders_restaurant_id_created_at", "orders", ["restaurant_id", "created_at"], unique=False
    )
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_index("ix_orders_restaurant_id_created_at", table_name="orders")
