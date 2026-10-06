"""Live Rider Tracking Phase 3/4 — add assignment_id, order_id, altitude,
captured_at to rider_location_pings

Revision ID: 20261006_48
Revises: 20261005_47
Create Date: 2026-10-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_48"
down_revision: Union[str, Sequence[str], None] = "20261005_47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("rider_location_pings") as batch_op:
        batch_op.add_column(sa.Column("assignment_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("order_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("altitude", sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_rider_location_pings_assignment_id", "delivery_assignments", ["assignment_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key("fk_rider_location_pings_order_id", "orders", ["order_id"], ["id"], ondelete="SET NULL")

    op.create_index(
        op.f("ix_rider_location_pings_assignment_id"), "rider_location_pings", ["assignment_id"], unique=False
    )
    op.create_index(op.f("ix_rider_location_pings_order_id"), "rider_location_pings", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rider_location_pings_order_id"), table_name="rider_location_pings")
    op.drop_index(op.f("ix_rider_location_pings_assignment_id"), table_name="rider_location_pings")

    with op.batch_alter_table("rider_location_pings") as batch_op:
        batch_op.drop_constraint("fk_rider_location_pings_order_id", type_="foreignkey")
        batch_op.drop_constraint("fk_rider_location_pings_assignment_id", type_="foreignkey")
        batch_op.drop_column("captured_at")
        batch_op.drop_column("altitude")
        batch_op.drop_column("order_id")
        batch_op.drop_column("assignment_id")
