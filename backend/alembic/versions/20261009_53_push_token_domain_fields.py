"""push token domain fields (device_identifier, is_active, last_seen_at, updated_at)

Revision ID: 20261009_53
Revises: 20261008_52
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_53"
down_revision: Union[str, Sequence[str], None] = "20261008_52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("push_tokens", sa.Column("device_identifier", sa.String(255), nullable=True))
    op.add_column(
        "push_tokens", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    # Backfilled from created_at (every existing row was, by definition,
    # last seen at least at the moment it was created) rather than left
    # NULL — a push token domain that "supports multiple devices per
    # user" needs last_seen_at to be a reliable staleness signal for
    # every row, not just ones created after this migration.
    op.add_column("push_tokens", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE push_tokens SET last_seen_at = created_at")
    op.alter_column("push_tokens", "last_seen_at", nullable=False)

    op.add_column(
        "push_tokens",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_push_tokens_device_identifier", "push_tokens", ["device_identifier"], unique=False)
    op.create_index("ix_push_tokens_is_active", "push_tokens", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_push_tokens_is_active", table_name="push_tokens")
    op.drop_index("ix_push_tokens_device_identifier", table_name="push_tokens")

    op.drop_column("push_tokens", "updated_at")
    op.drop_column("push_tokens", "last_seen_at")
    op.drop_column("push_tokens", "is_active")
    op.drop_column("push_tokens", "device_identifier")
