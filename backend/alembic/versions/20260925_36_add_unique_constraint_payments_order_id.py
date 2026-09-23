"""add unique constraint on payments.order_id

Revision ID: 20260925_36
Revises: 20260924_35
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260925_36"
down_revision: Union[str, Sequence[str], None] = "20260924_35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_payments_order_id", "payments", ["order_id"])


def downgrade() -> None:
    op.drop_constraint("uq_payments_order_id", "payments", type_="unique")
