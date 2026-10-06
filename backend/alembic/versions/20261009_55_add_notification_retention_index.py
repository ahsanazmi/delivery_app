"""add notification retention index (is_read, created_at)

Revision ID: 20261009_55
Revises: 20261009_54
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261009_55"
down_revision: Union[str, Sequence[str], None] = "20261009_54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_notifications_is_read_created_at", "notifications", ["is_read", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_is_read_created_at", table_name="notifications")
