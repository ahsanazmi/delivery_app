"""add delivery radius

Revision ID: 20261012_59
Revises: 20261012_58
Create Date: 2026-10-12

A platform-wide default delivery radius (5 km) plus an optional
per-restaurant override. Customers only see restaurants whose radius covers
their location, and checkout rejects addresses outside it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_59"
down_revision: Union[str, Sequence[str], None] = "20261012_58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("platform_settings") as batch_op:
        batch_op.add_column(
            sa.Column("default_delivery_radius_km", sa.Numeric(precision=5, scale=2), nullable=False, server_default="5.00")
        )

    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(sa.Column("delivery_radius_km", sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.create_check_constraint(
            "ck_restaurants_delivery_radius_positive",
            "delivery_radius_km IS NULL OR delivery_radius_km > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_constraint("ck_restaurants_delivery_radius_positive", type_="check")
        batch_op.drop_column("delivery_radius_km")

    with op.batch_alter_table("platform_settings") as batch_op:
        batch_op.drop_column("default_delivery_radius_km")
