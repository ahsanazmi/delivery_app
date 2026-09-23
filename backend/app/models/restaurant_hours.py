import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RestaurantOperatingHours(Base):
    """One row per day of the week for a restaurant. day_of_week follows
    Python's date.weekday() convention: 0=Monday .. 6=Sunday.

    A restaurant with zero rows here has never configured hours — checkout
    then falls back to the plain manual is_open toggle, so this feature is
    opt-in and never silently blocks orders for a restaurant that hasn't set
    hours up yet.
    """

    __tablename__ = "restaurant_operating_hours"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "day_of_week", name="uq_restaurant_hours_restaurant_day"),
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_restaurant_hours_day_of_week_range"),
        Index("ix_restaurant_operating_hours_restaurant_id", "restaurant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    close_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
