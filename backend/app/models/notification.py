import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Text, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(str, enum.Enum):
    # Notification Event Integration (Phase 20) — the order-placed
    # confirmation and the picked-up milestone previously had no
    # notification type at all (see the "no matching type in the spec"
    # note that used to live on _ORDER_STATUS_NOTIFICATIONS); both have a
    # real, already-firing trigger (create_order, pickup_delivery), so
    # this closes the two genuine gaps in this phase's own checklist.
    ORDER_PLACED = "order_placed"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_PREPARING = "order_preparing"
    ORDER_READY = "order_ready"
    RIDER_ASSIGNED = "rider_assigned"
    ORDER_PICKED_UP = "order_picked_up"
    ORDER_OUT_FOR_DELIVERY = "order_out_for_delivery"
    ORDER_DELIVERED = "order_delivered"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    PROMOTION = "promotion"
    SYSTEM = "system"
    # Rider Portal (Phase 21) — same table, same user_id-scoped model; a
    # rider is a user like any other, so no separate notifications table is
    # needed for them.
    NEW_DELIVERY = "new_delivery"
    DELIVERY_CANCELLED = "delivery_cancelled"
    DELIVERY_UPDATED = "delivery_updated"
    PAYMENT_UPDATE = "payment_update"
    EARNING_UPDATE = "earning_update"
    ACCOUNT_APPROVED = "account_approved"
    ACCOUNT_SUSPENDED = "account_suspended"
    # Admin Portal Phase 20 — operational alerts broadcast to every admin
    # user (see notify_admins in services/notifications.py), not scoped to
    # any one non-admin user the way every type above is.
    NEW_RESTAURANT_REGISTERED = "new_restaurant_registered"
    NEW_RIDER_REGISTERED = "new_rider_registered"
    DOCUMENT_SUBMITTED = "document_submitted"
    ORDER_ISSUE = "order_issue"
    PAYMENT_FAILURE = "payment_failure"
    COD_SETTLEMENT_DUE = "cod_settlement_due"
    # No automatic trigger produces this one yet in this phase — kept
    # available for a genuine platform-level issue a future feature might
    # need to raise, rather than inventing a contrived trigger just to
    # exercise it (see the Phase 20 completion report).
    SYSTEM_ALERT = "system_alert"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_is_read", "user_id", "is_read"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
