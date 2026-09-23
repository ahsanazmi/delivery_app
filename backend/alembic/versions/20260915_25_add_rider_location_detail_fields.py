"""add rider location detail fields and history table

Revision ID: 20260915_25
Revises: 20260915_24
Create Date: 2026-09-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_25"
down_revision: Union[str, Sequence[str], None] = "20260915_24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("current_accuracy", sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column("current_heading", sa.Numeric(precision=6, scale=2), nullable=True))
        batch_op.add_column(sa.Column("current_speed", sa.Numeric(precision=8, scale=2), nullable=True))

    op.create_table(
        "rider_location_pings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("accuracy", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("heading", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("speed", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rider_location_pings_rider_id"), "rider_location_pings", ["rider_id"], unique=False)
    op.create_index(
        "ix_rider_location_pings_rider_id_recorded_at", "rider_location_pings", ["rider_id", "recorded_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_rider_location_pings_rider_id_recorded_at", table_name="rider_location_pings")
    op.drop_index(op.f("ix_rider_location_pings_rider_id"), table_name="rider_location_pings")
    op.drop_table("rider_location_pings")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("current_speed")
        batch_op.drop_column("current_heading")
        batch_op.drop_column("current_accuracy")
