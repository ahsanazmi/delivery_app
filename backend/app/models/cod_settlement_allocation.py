import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CodSettlementAllocation(Base):
    """Financial Ledger Validation (Phase 30) — the link admin_settle_cod()
    was missing: which specific CodCollection row(s) a given RiderSettlement
    actually discharges, and how much of each. A settlement is a lump sum
    against a rider's aggregate outstanding balance, but a single
    collection can be split across more than one settlement (a partial
    settlement leaves the remainder outstanding for a later one) and a
    single settlement can cover more than one collection — so this is a
    genuine many-to-many join with its own amount, not a simple foreign
    key on either side.

    Allocated FIFO (oldest CodCollection first) at settlement time — see
    admin_settle_cod(). Append-only, like every other ledger in this
    codebase: never updated or deleted once written."""

    __tablename__ = "cod_settlement_allocations"
    __table_args__ = (
        CheckConstraint("amount_allocated > 0", name="ck_cod_settlement_allocations_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rider_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cod_collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cod_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_allocated: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
