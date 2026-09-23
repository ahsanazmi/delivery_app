"""create restaurant_operating_hours

Revision ID: 20260910_10
Revises: 20260910_09
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_10"
down_revision: Union[str, Sequence[str], None] = "20260910_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restaurant_operating_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "day_of_week", name="uq_restaurant_hours_restaurant_day"),
        sa.CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_restaurant_hours_day_of_week_range"),
    )
    op.create_index(
        op.f("ix_restaurant_operating_hours_restaurant_id"),
        "restaurant_operating_hours",
        ["restaurant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_restaurant_operating_hours_restaurant_id"), table_name="restaurant_operating_hours")
    op.drop_table("restaurant_operating_hours")
