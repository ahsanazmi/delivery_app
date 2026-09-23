"""add rejection_reason to restaurants

Revision ID: 20260918_29
Revises: 20260917_28
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_29"
down_revision: Union[str, Sequence[str], None] = "20260917_28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("restaurants", "rejection_reason")
