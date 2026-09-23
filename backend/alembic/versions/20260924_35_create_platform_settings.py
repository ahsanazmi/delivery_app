"""create platform_settings table

Revision ID: 20260924_35
Revises: 20260923_34
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_35"
down_revision: Union[str, Sequence[str], None] = "20260923_34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_name", sa.String(length=160), nullable=False, server_default="Say Hi Chai"),
        sa.Column("support_email", sa.String(length=255), nullable=True),
        sa.Column("support_phone", sa.String(length=20), nullable=True),
        sa.Column("default_delivery_fee", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("default_minimum_order", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("maintenance_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
