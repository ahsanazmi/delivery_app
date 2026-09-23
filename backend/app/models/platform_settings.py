import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlatformSettings(Base):
    """Admin Portal Phase 22 — a single, lazily-created row of platform-wide
    configuration (see get_platform_settings, which mirrors the same
    get-or-create pattern get_or_create_delivery_partner already uses for a
    per-user lazily-created row). Deliberately holds only non-secret,
    business-facing values an admin might reasonably change at runtime —
    never infrastructure/secrets (JWT keys, DB URL, payment-provider
    credentials), which stay in app.core.config.Settings, read from the
    environment, per this phase's own instruction.

    "Default commission" is intentionally NOT a column here — Phase 17's
    CommissionRule(restaurant_id=NULL) already owns that value; duplicating
    it here would create two sources of truth for the same figure."""

    __tablename__ = "platform_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    platform_name: Mapped[str] = mapped_column(String(160), default="Say Hi Chai", nullable=False)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Order configuration — used only as the fallback a new restaurant gets
    # when an admin/owner doesn't specify their own value at creation time
    # (see create_restaurant); never overwrites an existing restaurant's own
    # figure.
    default_delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    default_minimum_order: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)

    # Notification configuration — a platform-wide kill switch. When False,
    # notify_order_status_change / notify_riders_of_new_delivery /
    # broadcast_promotion / notify_admins all become no-ops (see
    # services/notifications.py).
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Business rule — when True, blocks placing any new order platform-wide
    # (see services/checkout.py's _checkout_issues), the same way an
    # unserviceable address already blocks checkout.
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
