import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.payment import PaymentProvider


class WebhookEvent(Base):
    """Payment Webhooks (Phase 17) — a durable, append-only record of
    every webhook this backend ever received from a payment provider,
    independent of whatever Payment/Refund row (if any) it ended up
    acting on. Exists specifically so "did we get this webhook, and what
    did we do with it" is answerable later, even for an event that
    couldn't be matched to a known payment at all (payment_id is
    deliberately nullable for exactly that case) — a plain PaymentAttempt
    row can't represent that, since its own payment_id is required.

    Only ever written *after* the request's HMAC signature has already
    been verified (see the /payments/webhooks/razorpay endpoint) — an
    unsigned or forged request never reaches this table at all.

    payment_id uses ON DELETE SET NULL rather than CASCADE: nothing in
    this codebase ever deletes a Payment row, but if that ever changed,
    the webhook's own audit history should still survive it — a payment
    disappearing is not a reason to also lose the record of what this
    backend was told about it.

    Webhook Idempotency (Phase 18) — event_id is Razorpay's own
    `x-razorpay-event-id` request header, unique per event delivery per
    Razorpay's own docs. It is the real "same event twice -> processed
    once" guarantee: process_webhook_event() checks for an existing row
    with this id *before* doing any event-specific work, and the unique
    constraint below is what makes that check-then-insert race-proof
    under two genuinely concurrent deliveries of the same event (same
    IntegrityError-catch-and-recover pattern already used for
    uq_payments_order_id and uq_payment_attempts_provider_payment_id).
    Nullable and NULL-safe (a NULL never collides with another NULL) for
    the same reason every other provider-id uniqueness constraint in this
    codebase is: a delivery this backend couldn't extract an id from
    (or, in tests, one that doesn't set the header) is never blocked from
    being recorded by some other id-less row."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Razorpay's own event name, e.g. "payment.captured", "payment.failed",
    # "refund.processed" — stored verbatim rather than mapped onto a closed
    # enum, since Razorpay adds new event types over time and an event this
    # backend doesn't yet act on should still be recorded, not rejected.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A short machine-readable summary of what this event actually caused —
    # "payment_marked_paid", "duplicate_ignored", "payment_not_found",
    # "amount_mismatch", "refund_marked_completed", "unhandled_event_type",
    # etc. Never null: every received (i.e. signature-verified) webhook is
    # classified as *something*, even if that something is "we did nothing".
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    # The verified request body, verbatim, for forensic/reconciliation use.
    # Razorpay webhook payloads never include the key secret or any
    # customer payment-instrument details (card/UPI numbers) — safe to
    # retain as-is, unlike a signature or secret.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
