import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    # Payment System Phase 2 — added alongside PaymentAttempt/Refund rather
    # than replacing anything: an existing Payment row sitting between
    # "the customer opened checkout" and "Razorpay actually responded" has
    # nowhere honest to live in the original five-value enum (PENDING
    # already means "not yet acted on", not "actively being processed").
    # PARTIALLY_REFUNDED likewise has nowhere to live now that Refund can
    # represent more than one refund against the same payment. CANCELLED
    # was already present on admin-web's own AdminPaymentStatusValue type
    # (see Phase 1's gap report) with no backend value to match — added
    # here to close that gap, not to invent a new one.
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class PaymentProvider(str, enum.Enum):
    RAZORPAY = "razorpay"
    COD = "cod"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Integration Phase 12 — exactly one payment record per order, ever.
        # Every code path that creates a Payment (record_order_payment,
        # collect_cod_payment, the legacy create_payment endpoint) already
        # find-or-creates against order_id as if this were true; this makes
        # it a real, portable (SQLite + Postgres) guarantee instead of an
        # unenforced convention, closing the check-then-insert race between
        # two near-simultaneous requests for the same order.
        UniqueConstraint("order_id", name="uq_payments_order_id"),
        CheckConstraint("amount >= 0", name="ck_payments_amount_nonnegative"),
        # Database Migrations (Phase 3) — a real Razorpay payment_id/order_id
        # must never be claimable by more than one Payment row. Without
        # this, a captured, genuinely-valid (razorpay_order_id,
        # razorpay_payment_id, signature) triple from one real transaction
        # could be replayed against a *different* Payment row — the HMAC
        # signature alone only proves the triple came from Razorpay, not
        # that it hasn't already been used to mark a different order paid.
        # Standard SQL/Postgres/SQLite all treat NULL as distinct from every
        # other NULL in a unique constraint, so this never blocks two COD
        # rows or two not-yet-verified Razorpay rows (both leave these
        # columns NULL) — it only ever blocks a real id being reused.
        # Scoped by (provider, id) rather than the id alone so a future
        # second online provider's own id namespace can't collide with
        # Razorpay's.
        UniqueConstraint("provider", "razorpay_order_id", name="uq_payments_provider_order_id"),
        UniqueConstraint("provider", "razorpay_payment_id", name="uq_payments_provider_payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=PaymentProvider.RAZORPAY,
        nullable=False,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refund_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set only by the rider-facing COD collection endpoint (Phase 16) — an
    # audit trail of which rider physically collected the cash and when,
    # distinct from payment_status/updated_at which don't say who acted.
    # Phase 30: indexed — the wallet's total_cod_collected sum
    # (rider_wallet.py) filters on this column, and it had no index at all
    # before, meaning that query did a full table scan of payments.
    collected_by_rider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Payment System Phase 2 — distinct from updated_at (which moves on any
    # change to this row, e.g. a failed verification attempt) and distinct
    # from created_at (set the moment the row is first opened, long before
    # money has actually changed hands for an online payment). Nullable and
    # unset by any code path yet — populating it is the service-layer work
    # of a later phase in this protocol, the same "field exists before
    # anything writes it" pattern RiderEarning's own INCENTIVE/BONUS/
    # ADJUSTMENT types already established in this codebase.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="payments")
    attempts: Mapped[list["PaymentAttempt"]] = relationship(
        "PaymentAttempt", back_populates="payment", cascade="all, delete-orphan"
    )
    refunds: Mapped[list["Refund"]] = relationship("Refund", back_populates="payment", cascade="all, delete-orphan")
