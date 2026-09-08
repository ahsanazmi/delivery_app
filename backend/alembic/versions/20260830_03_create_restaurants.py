"""create restaurants table

Revision ID: 20260830_03
Revises: 20260830_02
Create Date: 2026-08-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_03"
down_revision: Union[str, Sequence[str], None] = "20260830_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("logo_url", sa.String(length=2048), nullable=True),
        sa.Column("cover_image_url", sa.String(length=2048), nullable=True),
        sa.Column("minimum_order", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("average_rating", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("minimum_order >= 0", name="ck_restaurants_minimum_order_nonnegative"),
        sa.CheckConstraint("delivery_fee >= 0", name="ck_restaurants_delivery_fee_nonnegative"),
        sa.CheckConstraint("average_rating >= 0 AND average_rating <= 5", name="ck_restaurants_average_rating_range"),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_restaurants_latitude_range"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_restaurants_longitude_range"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restaurants_name", "restaurants", ["name"], unique=False)
    op.create_index("ix_restaurants_owner_id", "restaurants", ["owner_id"], unique=False)
    op.create_index("ix_restaurants_active_open", "restaurants", ["is_active", "is_open"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_restaurants_active_open", table_name="restaurants")
    op.drop_index("ix_restaurants_owner_id", table_name="restaurants")
    op.drop_index("ix_restaurants_name", table_name="restaurants")
    op.drop_table("restaurants")
