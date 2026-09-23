import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    RESTAURANT_OWNER = "RESTAURANT_OWNER"
    RIDER = "RIDER"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_role", "role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=UserRole.CUSTOMER,
    )
    profile_image: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Rider-only fields (no separate Rider table exists — a rider is just a
    # User with role=RIDER). Null for every other role and for a rider who
    # hasn't reported a location yet.
    current_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    current_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Phase 22 — cached alongside lat/lng as the cheap "last known position"
    # snapshot that list_available_deliveries and the customer tracking
    # snapshot read directly; the durable, throttled history of every
    # accepted ping lives separately in RiderLocationPing.
    current_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    current_heading: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    current_speed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
