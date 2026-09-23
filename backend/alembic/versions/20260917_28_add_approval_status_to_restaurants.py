"""add approval_status to restaurants

Revision ID: 20260917_28
Revises: 20260916_27
Create Date: 2026-09-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_28"
down_revision: Union[str, Sequence[str], None] = "20260916_27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    approval_status = postgresql.ENUM(
        "PENDING", "APPROVED", "REJECTED", "SUSPENDED",
        name="restaurant_approval_status",
        create_type=False,
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "restaurants",
        sa.Column("approval_status", approval_status, nullable=False, server_default="APPROVED"),
    )


def downgrade() -> None:
    op.drop_column("restaurants", "approval_status")
    postgresql.ENUM(name="restaurant_approval_status").drop(op.get_bind(), checkfirst=True)
