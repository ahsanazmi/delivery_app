"""add composite indexes for customer order history queries

Revision ID: 20260910_02
Revises: 20260910_01
Create Date: 2026-09-10

Phase 10 adds pagination + status/date filtering to GET /customer/orders,
which always scopes by user_id and either sorts by created_at or filters by
status — these composite indexes serve exactly those query shapes.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260910_02"
down_revision: Union[str, Sequence[str], None] = "20260910_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"], unique=False)
    op.create_index("ix_orders_user_id_status", "orders", ["user_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_user_id_status", table_name="orders")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
