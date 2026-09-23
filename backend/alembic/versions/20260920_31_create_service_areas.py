"""create service_areas and service_area_postal_codes tables

Revision ID: 20260920_31
Revises: 20260919_30
Create Date: 2026-09-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_31"
down_revision: Union[str, Sequence[str], None] = "20260919_30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_areas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("zone_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_service_areas_city"), "service_areas", ["city"], unique=False)

    op.create_table(
        "service_area_postal_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_area_id", sa.Uuid(), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["service_area_id"], ["service_areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("postal_code", name="uq_service_area_postal_codes_postal_code"),
    )
    op.create_index(
        op.f("ix_service_area_postal_codes_service_area_id"), "service_area_postal_codes", ["service_area_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_area_postal_codes_postal_code"), "service_area_postal_codes", ["postal_code"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_service_area_postal_codes_postal_code"), table_name="service_area_postal_codes")
    op.drop_index(op.f("ix_service_area_postal_codes_service_area_id"), table_name="service_area_postal_codes")
    op.drop_table("service_area_postal_codes")
    op.drop_index(op.f("ix_service_areas_city"), table_name="service_areas")
    op.drop_table("service_areas")
