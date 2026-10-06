"""add rider_approaching notification type

Revision ID: 20261006_49
Revises: 20261006_48
Create Date: 2026-10-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261006_49"
down_revision: Union[str, Sequence[str], None] = "20261006_48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'rider_approaching'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added label is left
    # in place on downgrade — same precedent as every other
    # enum-value-addition migration in this project.
    pass
