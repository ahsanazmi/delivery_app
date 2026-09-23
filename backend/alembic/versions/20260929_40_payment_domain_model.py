"""payment domain model — extend payment_status, add paid_at, payment_attempts, refunds

Revision ID: 20260929_40
Revises: 20260928_39
Create Date: 2026-09-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260929_40"
down_revision: Union[str, Sequence[str], None] = "20260928_39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_PAYMENT_STATUS_VALUES = (
    "processing",
    "cancelled",
    "partially_refunded",
)


def upgrade() -> None:
    for value in _NEW_PAYMENT_STATUS_VALUES:
        op.execute(f"ALTER TYPE payment_status ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column("payments", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))

    # Both payment_provider and payment_status already exist (created by
    # earlier migrations) — create_type=False + checkfirst=True references
    # them without attempting to redefine either type.
    payment_provider = postgresql.ENUM("razorpay", "cod", name="payment_provider", create_type=False)
    payment_provider.create(op.get_bind(), checkfirst=True)
    payment_status = postgresql.ENUM(
        "pending", "processing", "paid", "failed", "cancelled",
        "refund_pending", "partially_refunded", "refunded",
        name="payment_status", create_type=False,
    )
    payment_status.create(op.get_bind(), checkfirst=True)

    refund_status = postgresql.ENUM("pending", "processing", "completed", "failed", name="refund_status", create_type=False)
    refund_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", payment_provider, nullable=False),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount >= 0", name="ck_payment_attempts_amount_nonnegative"),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])

    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", refund_status, nullable=False),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount >= 0", name="ck_refunds_amount_nonnegative"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")

    op.drop_index("ix_payment_attempts_payment_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")

    postgresql.ENUM(name="refund_status").drop(op.get_bind(), checkfirst=True)

    op.drop_column("payments", "paid_at")

    # Postgres cannot drop individual enum values; the added payment_status
    # labels are left in place on downgrade — same precedent as every
    # other enum-value-addition migration in this project.
