"""create rider_earnings table

Revision ID: 20260915_22
Revises: 20260915_21
Create Date: 2026-09-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260915_22"
down_revision: Union[str, Sequence[str], None] = "20260915_21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    rider_earning_type = postgresql.ENUM(
        "DELIVERY_FEE", "INCENTIVE", "BONUS", "ADJUSTMENT",
        name="rider_earning_type",
        create_type=False,
    )
    rider_earning_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rider_earnings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("earning_type", rider_earning_type, nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rider_earnings_rider_id"), "rider_earnings", ["rider_id"], unique=False)
    op.create_index(op.f("ix_rider_earnings_order_id"), "rider_earnings", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rider_earnings_order_id"), table_name="rider_earnings")
    op.drop_index(op.f("ix_rider_earnings_rider_id"), table_name="rider_earnings")
    op.drop_table("rider_earnings")
    op.execute("DROP TYPE IF EXISTS rider_earning_type")
