"""add rating aggregation columns and indexes

Revision ID: 20261011_57
Revises: 20261010_56
Create Date: 2026-10-11

Reviews & Ratings Phase 6 — schema plumbing for the synchronous aggregation
recompute designed in docs/reviews-ratings-architecture.md §4: a plain
total_ratings counter alongside Restaurant.average_rating (which already
existed but was never paired with a count), and a new average_rating/
total_ratings pair on delivery_partners (the rider model), which had no
rating field at all. Also adds the two composite (target_id, status)
indexes on reviews that both the aggregation recompute and the Phase 3
moderated-list filter query against.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_57"
down_revision: Union[str, Sequence[str], None] = "20261010_56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(sa.Column("total_ratings", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_check_constraint(
            "ck_restaurants_total_ratings_nonnegative",
            "total_ratings >= 0",
        )

    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.add_column(sa.Column("average_rating", sa.Numeric(precision=3, scale=2), nullable=False, server_default="0.00"))
        batch_op.add_column(sa.Column("total_ratings", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_check_constraint(
            "ck_delivery_partners_average_rating_range",
            "average_rating >= 0 AND average_rating <= 5",
        )
        batch_op.create_check_constraint(
            "ck_delivery_partners_total_ratings_nonnegative",
            "total_ratings >= 0",
        )

    with op.batch_alter_table("reviews") as batch_op:
        batch_op.create_index("ix_reviews_restaurant_id_status", ["restaurant_id", "status"])
        batch_op.create_index("ix_reviews_rider_id_status", ["rider_id", "status"])


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_index("ix_reviews_rider_id_status")
        batch_op.drop_index("ix_reviews_restaurant_id_status")

    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.drop_constraint("ck_delivery_partners_total_ratings_nonnegative", type_="check")
        batch_op.drop_constraint("ck_delivery_partners_average_rating_range", type_="check")
        batch_op.drop_column("total_ratings")
        batch_op.drop_column("average_rating")

    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_constraint("ck_restaurants_total_ratings_nonnegative", type_="check")
        batch_op.drop_column("total_ratings")
