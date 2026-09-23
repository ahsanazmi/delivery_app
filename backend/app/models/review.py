import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReviewTarget(str, enum.Enum):
    RESTAURANT = "restaurant"
    FOOD = "food"
    RIDER = "rider"


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
        CheckConstraint(
            "restaurant_rating IS NULL OR (restaurant_rating >= 1 AND restaurant_rating <= 5)",
            name="ck_reviews_restaurant_rating_range",
        ),
        CheckConstraint(
            "delivery_rating IS NULL OR (delivery_rating >= 1 AND delivery_rating <= 5)",
            name="ck_reviews_delivery_rating_range",
        ),
        UniqueConstraint("order_id", name="uq_reviews_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=True, index=True)
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    target_type: Mapped[ReviewTarget] = mapped_column(
        Enum(ReviewTarget, name="review_target_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One order-review per order (Phase 16): restaurant_rating/delivery_rating
    # are the two dimensions the customer actually rates. `rating`/`target_type`/
    # `target_id` above stay populated too (mirroring restaurant_rating) so the
    # older generic per-target review endpoints keep working unchanged.
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    restaurant_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
