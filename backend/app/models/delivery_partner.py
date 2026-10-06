import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class VehicleType(str, enum.Enum):
    BIKE = "BIKE"
    SCOOTER = "SCOOTER"
    BICYCLE = "BICYCLE"
    OTHER = "OTHER"


class DeliveryPartner(Base):
    """A rider's onboarding/verification record — separate from User because
    it's specifically about the *delivery-partner* application (approval
    status, and later documents/vehicle/rating), not the account itself.
    One row per rider, created lazily (get_or_create) the first time it's
    needed rather than at registration, so every RIDER account — including
    ones created before this table existed — always has a well-defined
    status instead of needing a backfill migration."""

    __tablename__ = "delivery_partners"
    __table_args__ = (
        CheckConstraint("average_rating >= 0 AND average_rating <= 5", name="ck_delivery_partners_average_rating_range"),
        CheckConstraint("total_ratings >= 0", name="ck_delivery_partners_total_ratings_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="rider_approval_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=ApprovalStatus.PENDING,
        nullable=False,
    )
    # Only meaningful when approval_status == REJECTED — cleared on resubmission.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vehicle info (Phase 5) — all nullable since a fresh application hasn't
    # entered any of this yet; the frontend treats a null vehicle_type as
    # "not filled in" rather than defaulting to any particular vehicle.
    vehicle_type: Mapped[VehicleType | None] = mapped_column(
        Enum(VehicleType, name="rider_vehicle_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=True,
    )
    vehicle_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Phase 6 — the actual "available for deliveries" toggle. Enforced at
    # the point it's set (set_rider_online_status): can only ever become
    # True while approval_status == APPROVED, and is forced back to False
    # by the admin the moment a rider is moved to any non-APPROVED status
    # (see update_rider_verification) — so a suspended rider can never be
    # left showing as online.
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Reviews & Ratings Phase 6 — same shape as Restaurant.average_rating/
    # total_ratings: kept in sync by the synchronous aggregation recompute
    # (Phase 25-27) over this rider's PUBLISHED Review rows
    # (Review.rider_id -> users.id -> this row's user_id).
    average_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.00"), nullable=False)
    total_ratings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
