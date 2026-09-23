"""create delivery_partners table

Revision ID: 20260913_13
Revises: 20260911_12
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_13"
down_revision: Union[str, Sequence[str], None] = "20260911_12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    approval_status = postgresql.ENUM(
        "PENDING", "APPROVED", "REJECTED", "SUSPENDED",
        name="rider_approval_status",
        create_type=False,
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "delivery_partners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("approval_status", approval_status, nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_delivery_partners_user_id"), "delivery_partners", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_partners_user_id"), table_name="delivery_partners")
    op.drop_table("delivery_partners")
    postgresql.ENUM(name="rider_approval_status").drop(op.get_bind(), checkfirst=True)
