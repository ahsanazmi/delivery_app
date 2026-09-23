import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssignmentStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    # Phase 13 — the rider's own step-by-step progress once accepted.
    # Neither of these touches Order.status: ARRIVED_AT_RESTAURANT is purely
    # informational (Order stays RIDER_ASSIGNED), and PICKED_UP here just
    # mirrors the moment Order.status itself moves to PICKED_UP (an existing,
    # unchanged OrderStatus value/transition — see pickup_delivery()).
    ARRIVED_AT_RESTAURANT = "ARRIVED_AT_RESTAURANT"
    PICKED_UP = "PICKED_UP"
    # Phase 14 — mirrors the moment Order.status moves to OUT_FOR_DELIVERY
    # (an existing, unchanged transition — see start_delivery()).
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    # Phase 17 — mirrors the moment Order.status moves to DELIVERED
    # (an existing, unchanged transition — see complete_delivery()).
    DELIVERED = "DELIVERED"
    # Phase 24 — set automatically when the underlying Order is cancelled
    # while this rider still had a non-terminal assignment on it (see
    # _cancel_delivery_assignment in orders.py). Never set by a rider
    # action directly.
    CANCELLED = "CANCELLED"


class DeliveryAssignment(Base):
    """A record of one rider's progress on one order: their decision (accept
    or reject), and — once accepted — arrival and pickup.

    There is no persisted PENDING row — "pending" is the order's own
    unclaimed state (READY_FOR_PICKUP, rider_id IS NULL, see Phase 9's
    available-deliveries list), not something this table tracks. A row here
    only ever exists once a rider has actually acted, which keeps this table
    to real decisions rather than one row per rider per order ever shown.

    The row that matters for the "two riders must never both accept the same
    delivery" guarantee isn't this table at all — it's the atomic conditional
    UPDATE on Order.rider_id in accept_delivery(). This table is the
    after-the-fact record of who accepted/rejected/picked up what, not the
    locking mechanism itself.
    """

    __tablename__ = "delivery_assignments"
    __table_args__ = (
        # A given rider can only have one decision on file per order — a
        # second reject just updates rejected_at; there's no reason for two
        # rows to exist for the same (order, rider) pair.
        UniqueConstraint("order_id", "rider_id", name="uq_delivery_assignments_order_id_rider_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="delivery_assignment_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    out_for_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
