import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiderLocationPing(Base):
    """A throttled history of a rider's reported GPS positions.

    This is deliberately NOT one row per raw device update — see
    MIN_LOCATION_PING_INTERVAL_SECONDS in app/services/rider_location.py,
    which skips inserting a new row (while still refreshing the cheap
    "current position" cache on User and still broadcasting to any active
    tracker) when the last stored ping is too recent. Without that, a
    12-second foreground interval times every online rider, every day,
    would turn this into an unbounded, mostly-redundant table.

    User.current_latitude/current_longitude/current_accuracy/
    current_heading/current_speed/location_updated_at remains the fast path
    list_available_deliveries and the customer-facing tracking snapshot both
    read from directly — this table exists purely as the durable, lower-
    frequency ledger a prior phase asked for, not a replacement for that
    cache. It also doubles as this platform's "latest rider location"
    record in the sense Live Rider Tracking Phase 3 means: User's own
    columns are the fast-path cache (one row per rider, already uniquely
    keyed by its own primary key — no separate latest-location table is
    created here, per that phase's own "do not duplicate an existing
    location model"), and this table's own newest row per rider is the
    same information after the fact.

    Live Rider Tracking Phase 3 — assignment_id/order_id/altitude/
    captured_at added: assignment_id/order_id let a ping be tied back to
    which specific delivery it belonged to (both nullable — a rider who is
    online but not yet assigned anything still reports a position, for
    list_available_deliveries' own distance estimate, with nothing to tie
    it to yet); captured_at is the client's own claimed capture time,
    kept deliberately separate from recorded_at (the server's own receipt
    time) — never trusted on its own for ordering/throttling, but needed
    to detect an implausibly-old point (see services/rider_location.py's
    GPS accuracy/jump filtering).
    """

    __tablename__ = "rider_location_pings"
    __table_args__ = (
        Index("ix_rider_location_pings_rider_id_recorded_at", "rider_id", "recorded_at"),
        Index("ix_rider_location_pings_assignment_id", "assignment_id"),
        Index("ix_rider_location_pings_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delivery_assignments.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    heading: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    speed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    altitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # The device's own claimed capture time — optional (an older client
    # build may not send one), never trusted alone; see the module
    # docstring above.
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Server-assigned receipt time, not a client-supplied capture time — a
    # device clock can't be trusted for throttling decisions or for
    # ordering pings relative to each other.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
