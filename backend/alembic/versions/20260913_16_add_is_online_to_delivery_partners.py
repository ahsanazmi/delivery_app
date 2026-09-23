"""add is_online to delivery_partners

Revision ID: 20260913_16
Revises: 20260913_15
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_16"
down_revision: Union[str, Sequence[str], None] = "20260913_15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.add_column(sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.drop_column("is_online")
