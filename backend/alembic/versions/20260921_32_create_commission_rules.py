"""create commission_rules table and order commission snapshot columns

Revision ID: 20260921_32
Revises: 20260920_31
Create Date: 2026-09-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_32"
down_revision: Union[str, Sequence[str], None] = "20260920_31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    commission_type = postgresql.ENUM("PERCENTAGE", "FIXED", name="commission_type", create_type=False)
    commission_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "commission_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=True),
        sa.Column("commission_type", commission_type, nullable=False),
        sa.Column("value", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commission_rules_restaurant_id"), "commission_rules", ["restaurant_id"], unique=False)

    # Historical orders keep these NULL — no backfill, honestly reflecting
    # that no commission rule existed at the time they were placed.
    op.add_column("orders", sa.Column("commission_type", sa.String(length=16), nullable=True))
    op.add_column("orders", sa.Column("commission_rate", sa.Numeric(10, 2), nullable=True))
    op.add_column("orders", sa.Column("commission_amount", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "commission_amount")
    op.drop_column("orders", "commission_rate")
    op.drop_column("orders", "commission_type")
    op.drop_index(op.f("ix_commission_rules_restaurant_id"), table_name="commission_rules")
    op.drop_table("commission_rules")
    postgresql.ENUM(name="commission_type").drop(op.get_bind(), checkfirst=True)
