"""add coupon restaurant/customer eligibility, redemptions, cart coupon

Revision ID: 20260910_06
Revises: 20260910_05
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_06"
down_revision: Union[str, Sequence[str], None] = "20260910_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coupons") as batch_op:
        batch_op.add_column(sa.Column("restaurant_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("per_customer_limit", sa.Integer(), nullable=True, server_default="1"))
        batch_op.create_index(batch_op.f("ix_coupons_restaurant_id"), ["restaurant_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_coupons_restaurant_id_restaurants", "restaurants", ["restaurant_id"], ["id"], ondelete="CASCADE"
        )

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_coupon_redemptions_coupon_id"), "coupon_redemptions", ["coupon_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_user_id"), "coupon_redemptions", ["user_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_order_id"), "coupon_redemptions", ["order_id"], unique=False)

    with op.batch_alter_table("carts") as batch_op:
        batch_op.add_column(sa.Column("coupon_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_carts_coupon_id"), ["coupon_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_carts_coupon_id_coupons", "coupons", ["coupon_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("carts") as batch_op:
        batch_op.drop_constraint("fk_carts_coupon_id_coupons", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_carts_coupon_id"))
        batch_op.drop_column("coupon_id")

    op.drop_index(op.f("ix_coupon_redemptions_order_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_user_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_coupon_id"), table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")

    with op.batch_alter_table("coupons") as batch_op:
        batch_op.drop_constraint("fk_coupons_restaurant_id_restaurants", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_coupons_restaurant_id"))
        batch_op.drop_column("per_customer_limit")
        batch_op.drop_column("restaurant_id")
