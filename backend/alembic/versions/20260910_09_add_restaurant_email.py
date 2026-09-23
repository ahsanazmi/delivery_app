"""add email to restaurants

Revision ID: 20260910_09
Revises: 20260910_08
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_09"
down_revision: Union[str, Sequence[str], None] = "20260910_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("restaurants", "email")
