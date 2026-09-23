import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EarningType(str, enum.Enum):
    # Credited automatically whenever a rider completes a delivery (see
    # complete_delivery() in rider_deliveries.py) — one row per delivered
    # order, amount equal to that order's own delivery_fee.
    DELIVERY_FEE = "DELIVERY_FEE"
    # The remaining three exist so the ledger's shape is ready for whatever
    # future admin-driven incentive/bonus/adjustment program the master
    # architecture calls for — Phase 19 only asks for the rider-facing GET
    # endpoints, not a way to grant these, so nothing in this phase writes
    # rows of these types yet. See the Phase 19 completion report.
    INCENTIVE = "INCENTIVE"
    BONUS = "BONUS"
    ADJUSTMENT = "ADJUSTMENT"


class RiderEarning(Base):
    """An append-only ledger of everything that contributes to a rider's
    earnings. Never mutated after creation — a correction is a new
    ADJUSTMENT row (possibly negative), not an edit to an existing one, so
    the ledger stays a true history of what was credited and when."""

    __tablename__ = "rider_earnings"
    __table_args__ = (
        # Phase 30 — the earnings summary's today/week/month breakdowns
        # (rider_wallet.py's get_rider_earnings_summary) all filter
        # rider_id together with a created_at range; the single-column
        # rider_id index alone still leaves that range scan/sort unindexed.
        Index("ix_rider_earnings_rider_id_created_at", "rider_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Nullable: DELIVERY_FEE rows always reference the order they came from,
    # but a platform-wide INCENTIVE/BONUS/ADJUSTMENT need not tie to any one
    # delivery.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    earning_type: Mapped[EarningType] = mapped_column(
        Enum(EarningType, name="rider_earning_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    # Numeric/Decimal, never float — money. Can be negative for ADJUSTMENT
    # (e.g. a deduction), always non-negative for the other three types.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
