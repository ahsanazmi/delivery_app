"""create notification_preferences

Revision ID: 20261009_54
Revises: 20261009_53
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_54"
down_revision: Union[str, Sequence[str], None] = "20261009_53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("order_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("delivery_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("payment_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("promotions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user_id"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
