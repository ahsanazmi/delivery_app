import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.payment import PaymentProvider, PaymentStatus


class PaymentAttempt(Base):
    """Payment System Phase 2 — a single Payment row previously had nowhere
    to record the history of *trying*: a failed verification, a retry, a
    second attempt after the first timed out all just overwrote the same
    row's own failure_reason/payment_status in place, with no trace of
    what came before. One PaymentAttempt row is created per distinct
    attempt to actually collect this payment (each one owned by exactly
    one Payment — a Payment can have many attempts, an attempt belongs to
    exactly one Payment); nothing here mutates an existing attempt row
    after the provider has responded to it. Never written to directly by
    any endpoint — always through the payment service, the same way
    Payment itself already works.

    Provider identifiers are intentionally provider-generic
    (provider_order_id/provider_payment_id, not razorpay_*) — this is a
    brand-new model with no existing callers to preserve compatibility
    with, so it can use the vocabulary a future PaymentProvider
    abstraction actually needs from day one, unlike Payment's own existing
    razorpay_* columns (left as-is in this phase — renaming those is a
    provider-abstraction concern, not a domain-model one)."""

    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payment_attempts_amount_nonnegative"),
        # Database Migrations (Phase 3) — provider_payment_id is unique
        # (NULL-safe, scoped by provider — see Payment's own identical
        # reasoning): each real charge attempt at the provider gets its
        # own distinct id, and the same one must never be recorded twice.
        # provider_order_id is deliberately NOT unique here — a single
        # Razorpay *order* legitimately has more than one PaymentAttempt
        # against it (the customer's card was declined, they retried with
        # a different card, both attempts reference the same order id).
        # Making that unique would be exactly the "blindly created
        # constraint that prevents a legitimate retry" this phase warns
        # against.
        UniqueConstraint("provider", "provider_payment_id", name="uq_payment_attempts_provider_payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Snapshotted from the parent Payment's own amount at the moment this
    # attempt was made — never re-derived later, the same "snapshot once,
    # never retroactively recompute" principle Order.commission_amount and
    # OrderItem's own price fields already follow in this codebase.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    # A short, provider-defined machine-readable code (e.g. Razorpay's own
    # "BAD_REQUEST_ERROR" / "GATEWAY_ERROR" family) alongside the
    # human-readable message — kept as two separate columns so a future
    # dashboard can group/filter attempts by failure_code without parsing
    # failure_message's free text.
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    payment: Mapped["Payment"] = relationship("Payment", back_populates="attempts")
