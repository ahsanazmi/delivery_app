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
    frequency ledger Phase 22 asks for, not a replacement for that cache.
    """

    __tablename__ = "rider_location_pings"
    __table_args__ = (Index("ix_rider_location_pings_rider_id_recorded_at", "rider_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    heading: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    speed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # Server-assigned receipt time, not a client-supplied capture time — a
    # device clock can't be trusted for throttling decisions or for
    # ordering pings relative to each other.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
