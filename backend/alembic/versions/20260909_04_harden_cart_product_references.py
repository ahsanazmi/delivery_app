"""create carts/cart_items, referencing real products and restaurants

Revision ID: 20260909_04
Revises: 20260909_03
Create Date: 2026-09-09

The Cart/CartItem models existed in the codebase (and were exercised by the
SQLite-based test suite via Base.metadata.create_all) but no migration ever
created these tables against a real database — a pre-existing gap unrelated to
this change. Since there's nothing to migrate from, this creates them directly
with a hardened schema: `product_id`/`restaurant_id` are real foreign keys
(derived server-side from the product, never accepted from the client) rather
than the free-form strings the original in-code model briefly used.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_04"
down_revision: Union[str, Sequence[str], None] = "20260909_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_carts_user_id"), "carts", ["user_id"], unique=False)
    op.create_index(op.f("ix_carts_restaurant_id"), "carts", ["restaurant_id"], unique=False)

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(length=160), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cart_items_cart_id"), "cart_items", ["cart_id"], unique=False)
    op.create_index(op.f("ix_cart_items_product_id"), "cart_items", ["product_id"], unique=False)
    op.create_index(op.f("ix_cart_items_restaurant_id"), "cart_items", ["restaurant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cart_items_restaurant_id"), table_name="cart_items")
    op.drop_index(op.f("ix_cart_items_product_id"), table_name="cart_items")
    op.drop_index(op.f("ix_cart_items_cart_id"), table_name="cart_items")
    op.drop_table("cart_items")

    op.drop_index(op.f("ix_carts_restaurant_id"), table_name="carts")
    op.drop_index(op.f("ix_carts_user_id"), table_name="carts")
    op.drop_table("carts")
