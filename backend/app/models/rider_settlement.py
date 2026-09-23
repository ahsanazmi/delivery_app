import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SettlementType(str, enum.Enum):
    # Platform -> rider: paying out earnings the rider is owed.
    PAYOUT = "PAYOUT"
    # Rider -> platform: the rider handing back COD cash they've been
    # holding (see rider_wallet.py — that cash was never the rider's
    # income, so this is what actually clears the debt).
    REMITTANCE = "REMITTANCE"


class RiderSettlement(Base):
    """A record of real money having changed hands between the platform and
    a rider, in either direction. Append-only, like RiderEarning — a
    reversal is a new opposite-direction row, never an edit.

    Phase 20 only asks to *track* settlements, not to create them from the
    rider's own app (a rider settling their own account would defeat the
    purpose of a settlement as an independently-verified event) — there is
    no endpoint here that writes one yet. See the Phase 20 completion report.
    """

    __tablename__ = "rider_settlements"
    __table_args__ = (
        # Financial Consistency Test (Phase 23) — the docstring above
        # already documents amount as "always a positive magnitude"; this
        # makes that a real, enforced invariant rather than just a comment.
        CheckConstraint("amount >= 0", name="ck_rider_settlements_amount_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    settlement_type: Mapped[SettlementType] = mapped_column(
        Enum(SettlementType, name="rider_settlement_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    # Always a positive magnitude — settlement_type carries the direction.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
