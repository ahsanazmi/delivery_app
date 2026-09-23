"""create rider_settlements table

Revision ID: 20260915_23
Revises: 20260915_22
Create Date: 2026-09-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260915_23"
down_revision: Union[str, Sequence[str], None] = "20260915_22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    rider_settlement_type = postgresql.ENUM(
        "PAYOUT", "REMITTANCE",
        name="rider_settlement_type",
        create_type=False,
    )
    rider_settlement_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rider_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("settlement_type", rider_settlement_type, nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rider_settlements_rider_id"), "rider_settlements", ["rider_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rider_settlements_rider_id"), table_name="rider_settlements")
    op.drop_table("rider_settlements")
    op.execute("DROP TYPE IF EXISTS rider_settlement_type")
