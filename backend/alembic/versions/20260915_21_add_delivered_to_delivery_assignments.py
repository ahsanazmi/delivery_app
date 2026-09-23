"""add delivered field to delivery_assignments

Revision ID: 20260915_21
Revises: 20260914_20
Create Date: 2026-09-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_21"
down_revision: Union[str, Sequence[str], None] = "20260914_20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE delivery_assignment_status ADD VALUE IF NOT EXISTS 'DELIVERED'")

    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_assignments") as batch_op:
        batch_op.drop_column("delivered_at")

    # Postgres cannot drop individual enum values; the added label is left in
    # place on downgrade — same precedent as every other enum-value-addition
    # migration in this project.
