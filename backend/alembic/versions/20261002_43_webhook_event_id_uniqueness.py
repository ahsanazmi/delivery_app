"""webhook idempotency — add event_id column + uniqueness to webhook_events

Revision ID: 20261002_43
Revises: 20261001_42
Create Date: 2026-10-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_43"
down_revision: Union[str, Sequence[str], None] = "20261001_42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("webhook_events", sa.Column("event_id", sa.String(length=255), nullable=True))
    # NULL-safe (Postgres treats NULL as distinct from every other NULL in
    # a unique constraint) — a delivery this backend couldn't extract an
    # id from is never blocked by another id-less row; only a genuine,
    # non-null repeated event_id is ever rejected.
    op.create_unique_constraint("uq_webhook_events_provider_event_id", "webhook_events", ["provider", "event_id"])


def downgrade() -> None:
    op.drop_constraint("uq_webhook_events_provider_event_id", "webhook_events", type_="unique")
    op.drop_column("webhook_events", "event_id")
