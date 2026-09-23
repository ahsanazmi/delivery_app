"""add order-linked review fields

Revision ID: 20260910_05
Revises: 20260910_04
Create Date: 2026-09-10

Phase 16 needs one review per order with two rating dimensions
(restaurant_rating, delivery_rating), distinct from the pre-existing generic
per-target review system (target_type/target_id/rating), which stays intact
and unused-but-untouched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_05"
down_revision: Union[str, Sequence[str], None] = "20260910_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(sa.Column("order_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("restaurant_rating", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("delivery_rating", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_reviews_order_id"), ["order_id"], unique=False)
        batch_op.create_unique_constraint("uq_reviews_order_id", ["order_id"])
        batch_op.create_foreign_key(
            "fk_reviews_order_id_orders", "orders", ["order_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_check_constraint(
            "ck_reviews_restaurant_rating_range",
            "restaurant_rating IS NULL OR (restaurant_rating >= 1 AND restaurant_rating <= 5)",
        )
        batch_op.create_check_constraint(
            "ck_reviews_delivery_rating_range",
            "delivery_rating IS NULL OR (delivery_rating >= 1 AND delivery_rating <= 5)",
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint("ck_reviews_delivery_rating_range", type_="check")
        batch_op.drop_constraint("ck_reviews_restaurant_rating_range", type_="check")
        batch_op.drop_constraint("fk_reviews_order_id_orders", type_="foreignkey")
        batch_op.drop_constraint("uq_reviews_order_id", type_="unique")
        batch_op.drop_index("ix_reviews_order_id")
        batch_op.drop_column("delivery_rating")
        batch_op.drop_column("restaurant_rating")
        batch_op.drop_column("order_id")
