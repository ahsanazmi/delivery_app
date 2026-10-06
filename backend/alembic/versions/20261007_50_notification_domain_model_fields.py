"""notification domain model fields (role, data, channel, status, read_at, sent_at, failed_at)

Revision ID: 20261007_50
Revises: 20261006_49
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261007_50"
down_revision: Union[str, Sequence[str], None] = "20261006_49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    notification_channel = postgresql.ENUM("in_app", "push", name="notification_channel", create_type=False)
    notification_channel.create(op.get_bind(), checkfirst=True)

    notification_status = postgresql.ENUM("pending", "sent", "failed", name="notification_status", create_type=False)
    notification_status.create(op.get_bind(), checkfirst=True)

    # role: reuses the existing user_role enum (created by the users table's
    # own migration) — not re-created here, only referenced.
    user_role = postgresql.ENUM(
        "CUSTOMER", "RESTAURANT_OWNER", "RIDER", "ADMIN", name="user_role", create_type=False
    )

    # Added nullable first, backfilled from the recipient's own current
    # role, then tightened to NOT NULL — the safe sequence for adding a
    # required column to a table that may already hold rows, rather than a
    # single ALTER that would fail outright against any existing data.
    op.add_column("notifications", sa.Column("role", user_role, nullable=True))
    op.execute(
        """
        UPDATE notifications
        SET role = users.role
        FROM users
        WHERE users.id = notifications.user_id
        """
    )
    op.alter_column("notifications", "role", nullable=False)

    op.add_column("notifications", sa.Column("data", sa.JSON(), nullable=True))
    op.add_column(
        "notifications",
        sa.Column(
            "channel", notification_channel, nullable=False, server_default="in_app"
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "status", notification_status, nullable=False, server_default="pending"
        ),
    )
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_type", "notifications", ["type"], unique=False)
    op.create_index("ix_notifications_status", "notifications", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_status", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")

    op.drop_column("notifications", "failed_at")
    op.drop_column("notifications", "sent_at")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "status")
    op.drop_column("notifications", "channel")
    op.drop_column("notifications", "data")
    op.drop_column("notifications", "role")

    sa.Enum(name="notification_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_channel").drop(op.get_bind(), checkfirst=True)
