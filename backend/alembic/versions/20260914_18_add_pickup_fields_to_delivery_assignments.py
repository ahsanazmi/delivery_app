"""add arrival/pickup fields to delivery_assignments

Revision ID: 20260914_18
Revises: 20260913_17
Create Date: 2026-09-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_18"
down_revision: Union[str, Sequence[str], None] = "20260913_17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE delivery_assignment_status ADD VALUE IF NOT EXISTS 'ARRIVED_AT_RESTAURANT'")
    op.execute("ALTER TYPE delivery_assignment_status ADD VALUE IF NOT EXISTS 'PICKED_UP'")

    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.add_column(sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.drop_column("picked_up_at")
        batch_op.drop_column("arrived_at")

    # Postgres cannot drop individual enum values; the added labels are left
    # in place on downgrade (harmless once the app code that used them is
    # reverted) — same precedent as every other enum-value-addition migration
    # in this project.
