import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ServiceArea(Base):
    """A platform-configured delivery zone (Admin Portal Phase 16) — a named
    area within a city/district that either is or isn't currently
    serviceable. The actual postal codes it covers live in
    ServiceAreaPostalCode, not as a comma-separated string here, so
    "is this pincode deliverable" can be answered with a single indexed
    lookup rather than parsing every zone's list in Python."""

    __tablename__ = "service_areas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    city: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zone_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Service availability — whether orders are currently accepted for the
    # postal codes under this zone. A zone can be configured ahead of time
    # and switched on later, or temporarily switched off without deleting
    # its postal code list.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    postal_codes: Mapped[list["ServiceAreaPostalCode"]] = relationship(
        back_populates="service_area", cascade="all, delete-orphan"
    )


class ServiceAreaPostalCode(Base):
    """One postal code covered by a ServiceArea. A postal code belongs to
    at most one zone — enforced with a unique constraint — so "is this
    pincode serviceable" is never ambiguous between two overlapping zones."""

    __tablename__ = "service_area_postal_codes"
    __table_args__ = (
        UniqueConstraint("postal_code", name="uq_service_area_postal_codes_postal_code"),
        Index("ix_service_area_postal_codes_service_area_id", "service_area_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_area_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_areas.id", ondelete="CASCADE"), nullable=False
    )
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    service_area: Mapped[ServiceArea] = relationship(back_populates="postal_codes")
