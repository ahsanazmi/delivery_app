import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.delivery_partner import ApprovalStatus


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        CheckConstraint("minimum_order >= 0", name="ck_restaurants_minimum_order_nonnegative"),
        CheckConstraint("delivery_fee >= 0", name="ck_restaurants_delivery_fee_nonnegative"),
        CheckConstraint("average_rating >= 0 AND average_rating <= 5", name="ck_restaurants_average_rating_range"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_restaurants_latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_restaurants_longitude_range"),
        Index("ix_restaurants_active_open", "is_active", "is_open"),
        Index("ix_restaurants_owner_id", "owner_id"),
        Index("ix_restaurants_category_id", "category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str] = mapped_column(Text)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    # Maps & Location System Phase 3 — same fields Phase 2 added to
    # Address, same reasoning: nullable, since every existing restaurant
    # already has a valid required lat/lng from manual entry and must
    # keep working unchanged; only populated once an owner actually
    # sets the location via the map/search flow (Phase 10).
    formatted_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    minimum_order: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    delivery_time_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    average_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.00"), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Admin Portal Phase 4 — a restaurant's standing with the platform,
    # separate from is_active (the owner's/admin's own on/off switch) and
    # is_open (a live hours toggle). Defaults to APPROVED so every existing
    # restaurant, and every one created through the normal owner-signup
    # flow, keeps operating exactly as before; only an explicit admin
    # action ever moves it away from that, and doing so is what actually
    # blocks the restaurant from customer listings/orders (see
    # get_active_restaurant_or_404). As of Phase 6, the only way to change
    # this is through the validated approve/reject/suspend/activate actions
    # in admin_restaurants.py — never a raw field write — so every
    # transition goes through the state machine there.
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="restaurant_approval_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=ApprovalStatus.APPROVED,
        server_default=ApprovalStatus.APPROVED.value,
        nullable=False,
    )
    # Phase 6 — only meaningful when approval_status == REJECTED, cleared on
    # any transition away from it. Same shape as DeliveryPartner.rejection_reason.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
