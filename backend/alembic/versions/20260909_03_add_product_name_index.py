"""add index on products.name for search

Revision ID: 20260909_03
Revises: 20260909_02
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260909_03"
down_revision: Union[str, Sequence[str], None] = "20260909_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f("ix_products_name"), "products", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_products_name"), table_name="products")
