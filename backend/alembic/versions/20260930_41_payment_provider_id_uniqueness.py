"""payment provider id uniqueness — payments, payment_attempts, refunds

Revision ID: 20260930_41
Revises: 20260929_40
Create Date: 2026-09-30

Adds NULL-safe uniqueness on the provider-issued identifiers that must
never be claimed by more than one of our own rows (a real Razorpay
payment_id/order_id/refund_id being reused across two different rows would
mean one real provider-side transaction got recorded — or replayed — as
two of ours). Deliberately does NOT add uniqueness to
payment_attempts.provider_order_id: a single provider order legitimately
has more than one attempt against it (a declined card followed by a
retry with a different one), and constraining that would block a
legitimate retry, not just a duplicate.

Postgres (and SQLite) both treat NULL as distinct from every other NULL in
a unique constraint, so none of this blocks COD rows or not-yet-verified
online rows, which leave these columns NULL.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260930_41"
down_revision: Union[str, Sequence[str], None] = "20260929_40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_payments_provider_order_id", "payments", ["provider", "razorpay_order_id"]
    )
    op.create_unique_constraint(
        "uq_payments_provider_payment_id", "payments", ["provider", "razorpay_payment_id"]
    )
    op.create_unique_constraint(
        "uq_payment_attempts_provider_payment_id", "payment_attempts", ["provider", "provider_payment_id"]
    )
    op.create_unique_constraint(
        "uq_refunds_provider_refund_id", "refunds", ["provider_refund_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_refunds_provider_refund_id", "refunds", type_="unique")
    op.drop_constraint("uq_payment_attempts_provider_payment_id", "payment_attempts", type_="unique")
    op.drop_constraint("uq_payments_provider_payment_id", "payments", type_="unique")
    op.drop_constraint("uq_payments_provider_order_id", "payments", type_="unique")
