"""payment webhooks — create webhook_events audit table

Revision ID: 20261001_42
Revises: 20260930_41
Create Date: 2026-10-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261001_42"
down_revision: Union[str, Sequence[str], None] = "20260930_41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payment_provider already exists (created by an earlier migration) —
    # create_type=False + checkfirst=True references it without attempting
    # to redefine it.
    payment_provider = postgresql.ENUM("razorpay", "cod", name="payment_provider", create_type=False)
    payment_provider.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", payment_provider, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("ix_webhook_events_provider_payment_id", "webhook_events", ["provider_payment_id"])
    op.create_index("ix_webhook_events_provider_order_id", "webhook_events", ["provider_order_id"])
    op.create_index("ix_webhook_events_payment_id", "webhook_events", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_payment_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider_order_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider_payment_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
