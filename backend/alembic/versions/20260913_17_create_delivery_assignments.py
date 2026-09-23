"""create delivery_assignments table

Revision ID: 20260913_17
Revises: 20260913_16
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_17"
down_revision: Union[str, Sequence[str], None] = "20260913_16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    assignment_status = postgresql.ENUM(
        "ACCEPTED", "REJECTED",
        name="delivery_assignment_status",
        create_type=False,
    )
    assignment_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "delivery_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("status", assignment_status, nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "rider_id", name="uq_delivery_assignments_order_id_rider_id"),
    )
    op.create_index(op.f("ix_delivery_assignments_order_id"), "delivery_assignments", ["order_id"], unique=False)
    op.create_index(op.f("ix_delivery_assignments_rider_id"), "delivery_assignments", ["rider_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_assignments_rider_id"), table_name="delivery_assignments")
    op.drop_index(op.f("ix_delivery_assignments_order_id"), table_name="delivery_assignments")
    op.drop_table("delivery_assignments")
    postgresql.ENUM(name="delivery_assignment_status").drop(op.get_bind(), checkfirst=True)
