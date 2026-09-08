"""add rider_id to orders

Revision ID: 20260905_02
Revises: 20260905_01
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_02"
down_revision: Union[str, Sequence[str], None] = "20260905_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    order_status = sa.Enum(
        "pending",
        "confirmed",
        "preparing",
        "out_for_delivery",
        "delivered",
        "cancelled",
        name="order_status",
    )

    order_history_status = sa.Enum(
        "pending",
        "confirmed",
        "preparing",
        "out_for_delivery",
        "delivered",
        "cancelled",
        name="order_status_history_status",
    )

    if "orders" not in existing_tables:
        op.create_table(
            "orders",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("restaurant_id", sa.String(length=64), nullable=True),
            sa.Column("restaurant_name", sa.String(length=160), nullable=True),
            sa.Column("restaurant_phone", sa.String(length=20), nullable=True),
            sa.Column("order_number", sa.String(length=32), nullable=False),
            sa.Column("status", order_status, nullable=False, server_default="pending"),
            sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="cod"),
            sa.Column("subtotal", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
            sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
            sa.Column("total", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
            sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("address_line", sa.Text(), nullable=False),
            sa.Column("city", sa.String(length=120), nullable=False),
            sa.Column("state", sa.String(length=120), nullable=True),
            sa.Column("postal_code", sa.String(length=20), nullable=False),
            sa.Column("landmark", sa.String(length=200), nullable=True),
            sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column("delivery_instructions", sa.Text(), nullable=True),
            sa.Column("cancelled_reason", sa.Text(), nullable=True),
            sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("order_number"),
        )
        op.create_index(op.f("ix_orders_user_id"), "orders", ["user_id"], unique=False)
        op.create_index(op.f("ix_orders_restaurant_id"), "orders", ["restaurant_id"], unique=False)
        op.create_index(op.f("ix_orders_order_number"), "orders", ["order_number"], unique=True)

    if "order_items" not in existing_tables:
        op.create_table(
            "order_items",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("order_id", sa.Uuid(), nullable=False),
            sa.Column("product_id", sa.String(length=64), nullable=False),
            sa.Column("restaurant_id", sa.String(length=64), nullable=False),
            sa.Column("product_name", sa.String(length=160), nullable=False),
            sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)
        op.create_index(op.f("ix_order_items_product_id"), "order_items", ["product_id"], unique=False)
        op.create_index(op.f("ix_order_items_restaurant_id"), "order_items", ["restaurant_id"], unique=False)

    if "order_status_history" not in existing_tables:
        op.create_table(
            "order_status_history",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("order_id", sa.Uuid(), nullable=False),
            sa.Column("status", order_history_status, nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_order_status_history_order_id"), "order_status_history", ["order_id"], unique=False)

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("rider_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_orders_rider_id"), ["rider_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_orders_rider_id_users",
            "users",
            ["rider_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("fk_orders_rider_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_orders_rider_id"))
        batch_op.drop_column("rider_id")

    op.drop_table("order_status_history")
    op.drop_table("order_items")
    op.drop_table("orders")

    sa.Enum(name="order_status_history_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
