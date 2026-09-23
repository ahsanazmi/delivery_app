"""add rider performance indexes

Revision ID: 20260916_27
Revises: 20260915_26
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260916_27"
down_revision: Union[str, Sequence[str], None] = "20260915_26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_orders_rider_id_status", "orders", ["rider_id", "status"], unique=False)
    op.create_index(
        "ix_rider_earnings_rider_id_created_at", "rider_earnings", ["rider_id", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_payments_collected_by_rider_id"), "payments", ["collected_by_rider_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_collected_by_rider_id"), table_name="payments")
    op.drop_index("ix_rider_earnings_rider_id_created_at", table_name="rider_earnings")
    op.drop_index("ix_orders_rider_id_status", table_name="orders")
