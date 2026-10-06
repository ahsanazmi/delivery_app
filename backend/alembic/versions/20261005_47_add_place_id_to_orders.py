"""Maps & Location System Phase 12 — add place_id to orders (delivery
address snapshot)

Revision ID: 20261005_47
Revises: 20261004_46
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_47"
down_revision: Union[str, Sequence[str], None] = "20261004_46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("place_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("place_id")
