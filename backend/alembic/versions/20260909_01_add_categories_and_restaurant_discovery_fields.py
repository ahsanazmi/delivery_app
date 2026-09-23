"""add categories table and restaurant discovery fields

Revision ID: 20260909_01
Revises: 20260907_01
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_01"
down_revision: Union[str, Sequence[str], None] = "20260907_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_categories_name"), "categories", ["name"], unique=True)

    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("delivery_time_minutes", sa.Integer(), nullable=False, server_default="30"))
        batch_op.create_index(batch_op.f("ix_restaurants_category_id"), ["category_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_restaurants_category_id_categories", "categories", ["category_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_constraint("fk_restaurants_category_id_categories", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_restaurants_category_id"))
        batch_op.drop_column("delivery_time_minutes")
        batch_op.drop_column("category_id")

    op.drop_index(op.f("ix_categories_name"), table_name="categories")
    op.drop_table("categories")
