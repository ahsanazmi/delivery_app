import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CodCollection(Base):
    """Financial Ledger Validation (Phase 30) — an append-only ledger of
    every COD cash-collection event, one row inserted the moment a rider
    actually collects it (see collect_cod_payment() in
    rider_deliveries.py). Previously the only trace of "rider X collected
    cash for order Y at time T" was three mutated fields on the single
    per-order Payment row (collected_by_rider_id/collected_at/amount) —
    correct today, but not structurally protected the way every other
    financial movement in this codebase already is (PaymentAttempt for
    online payments, Refund for refunds, RiderEarning for delivery pay,
    RiderSettlement for settlements). This table closes that gap: once
    inserted, a row here is never updated or deleted — a correction would
    be a new, separate financial event, never an edit to what was
    actually collected.

    Also the ledger CodSettlementAllocation allocates against when an
    admin settles a rider's COD balance — see that model's own note."""

    __tablename__ = "cod_collections"
    __table_args__ = (
        # Exactly one collection event per Payment — a COD payment
        # transitions PENDING -> PAID exactly once (guarded server-side in
        # collect_cod_payment()); this makes "never double-collect the
        # same order's cash" a real, database-enforced guarantee too, not
        # just an application-level check.
        UniqueConstraint("payment_id", name="uq_cod_collections_payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
