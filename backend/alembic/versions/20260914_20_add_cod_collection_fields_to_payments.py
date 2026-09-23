"""add cod collection fields to payments

Revision ID: 20260914_20
Revises: 20260914_19
Create Date: 2026-09-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_20"
down_revision: Union[str, Sequence[str], None] = "20260914_19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("collected_by_rider_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_payments_collected_by_rider_id_users",
            "users",
            ["collected_by_rider_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("fk_payments_collected_by_rider_id_users", type_="foreignkey")
        batch_op.drop_column("collected_at")
        batch_op.drop_column("collected_by_rider_id")
