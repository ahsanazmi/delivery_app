"""add payments, reviews and coupons tables

Revision ID: 20260907_01
Revises: 20260905_02
Create Date: 2026-09-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_01"
down_revision: Union[str, Sequence[str], None] = "20260905_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    payment_status = postgresql.ENUM(
        "pending", "paid", "failed", "refund_pending", "refunded",
        name="payment_status",
        create_type=False,
    )
    payment_status.create(op.get_bind(), checkfirst=True)

    payment_provider = postgresql.ENUM("razorpay", "cod", name="payment_provider", create_type=False)
    payment_provider.create(op.get_bind(), checkfirst=True)

    coupon_discount_type = postgresql.ENUM("percent", "fixed", name="coupon_discount_type", create_type=False)
    coupon_discount_type.create(op.get_bind(), checkfirst=True)

    review_target_type = postgresql.ENUM("restaurant", "food", "rider", name="review_target_type", create_type=False)
    review_target_type.create(op.get_bind(), checkfirst=True)

    bind = op.get_bind()
    columns = sa.inspect(bind).get_columns("orders")
    column_names = {column["name"] for column in columns}
    if "payment_status" not in column_names:
        with op.batch_alter_table("orders") as batch_op:
            batch_op.add_column(sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="pending"))
            batch_op.create_index(batch_op.f("ix_orders_payment_status"), ["payment_status"], unique=False)

    op.create_table(
        "coupons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("discount_type", coupon_discount_type, nullable=False),
        sa.Column("discount_value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("min_order", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("max_discount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_coupons_code"), "coupons", ["code"], unique=True)

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", payment_provider, nullable=False, server_default="razorpay"),
        sa.Column("payment_status", payment_status, nullable=False, server_default="pending"),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("razorpay_order_id", sa.String(length=255), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(length=255), nullable=True),
        sa.Column("razorpay_signature", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("refund_id", sa.String(length=255), nullable=True),
        sa.Column("refund_status", sa.String(length=32), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"], unique=False)
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)

    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=True),
        sa.Column("rider_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", review_target_type, nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
    )
    op.create_index(op.f("ix_reviews_user_id"), "reviews", ["user_id"], unique=False)
    op.create_index(op.f("ix_reviews_restaurant_id"), "reviews", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_reviews_rider_id"), "reviews", ["rider_id"], unique=False)
    op.create_index(op.f("ix_reviews_target_id"), "reviews", ["target_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reviews_target_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_rider_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_restaurant_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_user_id"), table_name="reviews")
    op.drop_table("reviews")

    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_order_id"), table_name="payments")
    op.drop_table("payments")

    op.drop_index(op.f("ix_coupons_code"), table_name="coupons")
    op.drop_table("coupons")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("payment_status")

    sa.Enum(name="review_target_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="coupon_discount_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_provider").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_status").drop(op.get_bind(), checkfirst=True)
