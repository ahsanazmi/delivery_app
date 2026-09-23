"""add image_url to menu_categories

Revision ID: 20260910_11
Revises: 20260910_10
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_11"
down_revision: Union[str, Sequence[str], None] = "20260910_10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("menu_categories", sa.Column("image_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("menu_categories", "image_url")
