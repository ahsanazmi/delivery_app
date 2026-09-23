"""add vehicle fields to delivery_partners

Revision ID: 20260913_15
Revises: 20260913_14
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_15"
down_revision: Union[str, Sequence[str], None] = "20260913_14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    vehicle_type = postgresql.ENUM(
        "BIKE", "SCOOTER", "BICYCLE", "OTHER",
        name="rider_vehicle_type",
        create_type=False,
    )
    vehicle_type.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.add_column(sa.Column("vehicle_type", vehicle_type, nullable=True))
        batch_op.add_column(sa.Column("vehicle_number", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("vehicle_model", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_partners") as batch_op:
        batch_op.drop_column("vehicle_model")
        batch_op.drop_column("vehicle_number")
        batch_op.drop_column("vehicle_type")

    postgresql.ENUM(name="rider_vehicle_type").drop(op.get_bind(), checkfirst=True)
