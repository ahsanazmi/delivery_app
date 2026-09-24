"""Maps & Location System Phase 3 — add formatted_address, place_id to
restaurants

Revision ID: 20261004_46
Revises: 20261004_45
Create Date: 2026-10-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261004_46"
down_revision: Union[str, Sequence[str], None] = "20261004_45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(sa.Column("formatted_address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("place_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_column("place_id")
        batch_op.drop_column("formatted_address")
