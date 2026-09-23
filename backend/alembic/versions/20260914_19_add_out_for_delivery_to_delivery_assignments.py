"""add out_for_delivery field to delivery_assignments

Revision ID: 20260914_19
Revises: 20260914_18
Create Date: 2026-09-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_19"
down_revision: Union[str, Sequence[str], None] = "20260914_18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE delivery_assignment_status ADD VALUE IF NOT EXISTS 'OUT_FOR_DELIVERY'")

    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.add_column(sa.Column("out_for_delivery_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.drop_column("out_for_delivery_at")

    # Postgres cannot drop individual enum values; the added label is left in
    # place on downgrade — same precedent as every other enum-value-addition
    # migration in this project.
