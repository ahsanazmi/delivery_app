import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationPreference(Base):
    """Notification Preferences (Phase 24) — one row per user, created
    lazily (get_or_create_notification_preference) the first time it's
    needed rather than at registration, the same pattern DeliveryPartner
    already established: every account, including ones created before
    this table existed, always has a well-defined set of preferences
    without needing a backfill migration.

    Every column defaults to True — "default transactional notifications
    should remain enabled where necessary for service operation," and
    promotions defaults to True too so this table's own creation never
    silently narrows broadcast_promotion's existing reach (every active
    customer) the moment a user's row is first created; a user who
    actually wants fewer notifications turns a category off explicitly,
    this table never turns one off on their behalf.

    Deliberately does not cover admin accounts' own operational alerts
    (notify_admins) — those are job-function alerts tied to the ADMIN
    role itself, not a personal preference an admin should be able to
    silence, the same reasoning notify_admins's own _ADMIN_NOTIFICATION_
    TYPES validation already applies elsewhere."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    order_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    delivery_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payment_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    promotions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    system_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
