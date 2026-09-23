import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Refund(Base):
    """Payment System Phase 2 — previously a refund was just two loose
    string columns bolted onto Payment itself (refund_id/refund_status),
    with no way to represent more than one refund against the same
    payment, no amount of its own (a partial refund had nowhere to record
    how much), and no reason or timeline independent of the payment it
    came from. A Payment can have many Refunds (one per actual refund
    attempt/event); a Refund always belongs to exactly one Payment.

    order_id is denormalized onto this row (same convention as
    OrderItem.restaurant_id and Order's own customer/restaurant name
    snapshots elsewhere in this codebase) purely so admin refund queries
    can filter/join by order without an extra hop through Payment — it is
    never treated as more authoritative than payment.order_id.

    Nothing in this phase writes a Refund row yet — creating the model is
    this phase's whole scope; the admin-gated refund flow that actually
    populates it belongs to a later phase in this protocol (see Phase 1's
    gap report on the existing, ungated customer-facing refund endpoint
    that will need reconciling against this model then, not now)."""

    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_refunds_amount_nonnegative"),
        # Database Migrations (Phase 3) — a real refund id from the provider
        # must never be claimed by more than one Refund row (NULL-safe: a
        # Refund still in PENDING/PROCESSING before the provider has
        # actually issued one leaves this column NULL, and multiple such
        # rows never conflict). Not scoped by a provider column here —
        # unlike Payment/PaymentAttempt, Refund has no provider column of
        # its own (it's reachable via payment.provider); revisit this
        # constraint if a second refund-issuing provider is added later.
        UniqueConstraint("provider_refund_id", name="uq_refunds_provider_refund_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, name="refund_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=RefundStatus.PENDING,
        nullable=False,
    )
    provider_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    payment: Mapped["Payment"] = relationship("Payment", back_populates="refunds")
