"""Maps & Location System Phase 2 — add district, formatted_address,
place_id to addresses

Revision ID: 20261004_45
Revises: 20261003_44
Create Date: 2026-10-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261004_45"
down_revision: Union[str, Sequence[str], None] = "20261003_44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("addresses") as batch_op:
        batch_op.add_column(sa.Column("district", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("formatted_address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("place_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("addresses") as batch_op:
        batch_op.drop_column("place_id")
        batch_op.drop_column("formatted_address")
        batch_op.drop_column("district")
