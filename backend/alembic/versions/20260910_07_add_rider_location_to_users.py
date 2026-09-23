"""add rider live-location fields to users

Revision ID: 20260910_07
Revises: 20260910_06
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_07"
down_revision: Union[str, Sequence[str], None] = "20260910_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("current_latitude", sa.Numeric(10, 7), nullable=True))
        batch_op.add_column(sa.Column("current_longitude", sa.Numeric(10, 7), nullable=True))
        batch_op.add_column(sa.Column("location_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("location_updated_at")
        batch_op.drop_column("current_longitude")
        batch_op.drop_column("current_latitude")
