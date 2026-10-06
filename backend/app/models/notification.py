import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Text, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import UserRole


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
    # Live Rider Tracking Phase 34 — a proximity-triggered, not a status-
    # change-triggered, notification: fires once when the rider's live
    # position comes within RIDER_APPROACHING_DISTANCE_KM of the delivery
    # address while OUT_FOR_DELIVERY, not on any OrderStatus transition.
    RIDER_APPROACHING = "rider_approaching"
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
    # Notifications & Communication System Phase 5 — Notification Type
    # Catalog. Added ahead of a wired trigger, the same way SYSTEM_ALERT
    # and PAYMENT_UPDATE (before Phase 20's payment-failure trigger)
    # already were — online payment/refunds/restaurant-web notifications
    # are all genuinely reachable future features, not speculative
    # additions with no code path that will ever raise them. PAYMENT_SUCCESS
    # and the two REFUND_* types are dormant the same way PAYMENT_UPDATE
    # itself was before Phase 20 — see notify_customer_payment_failed's own
    # note on why online payment is currently unreachable
    # (payment_method is locked to "cod" at order creation).
    PAYMENT_SUCCESS = "payment_success"
    REFUND_INITIATED = "refund_initiated"
    REFUND_COMPLETED = "refund_completed"
    COD_PENDING = "cod_pending"
    COD_COLLECTED = "cod_collected"
    # For the business-web notification surface Phase 1's audit found does
    # not exist at all yet (Phase 12's job) — added to the catalog now so
    # that phase has a real type to raise against, rather than inventing
    # one ad hoc when it lands.
    RESTAURANT_NEW_ORDER = "restaurant_new_order"
    RESTAURANT_ORDER_CANCELLED = "restaurant_order_cancelled"
    # Notifications & Communication System Phase 11 — Rider Notification
    # Center's own "account/document alerts" checklist item named a real,
    # previously-unwired gap: a rider was
    # only ever told about their overall account approval/suspension
    # (ACCOUNT_APPROVED/ACCOUNT_SUSPENDED), never about an individual
    # document being approved or rejected (rider_documents.py's
    # update_document_verification only ever alerted admins on
    # *submission*, via DOCUMENT_SUBMITTED — the rider never heard back).
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_REJECTED = "document_rejected"

    # This phase's own example list also named RIDER_ACCEPTED,
    # RIDER_NEW_ASSIGNMENT, RIDER_ASSIGNMENT_CANCELLED, and ADMIN_ALERT —
    # deliberately NOT added as new values, per this phase's own
    # instruction to reconcile naming rather than scatter true duplicates
    # of one concept across two enum values (flagged as a likely conflict
    # back in docs/notification-system-audit.md's Phase 1 audit):
    #   - RIDER_ACCEPTED: in this codebase's actual rider-accept flow
    #     (accept_delivery, app/services/rider_deliveries.py), a rider
    #     claiming a delivery and the order transitioning to RIDER_ASSIGNED
    #     happen atomically, in the same call — there is no separate
    #     "accepted" moment distinct from "assigned" to notify about.
    #     RIDER_ASSIGNED already covers this exact event.
    #   - RIDER_NEW_ASSIGNMENT / RIDER_ASSIGNMENT_CANCELLED: the same
    #     concepts already exist as NEW_DELIVERY / DELIVERY_CANCELLED
    #     (Rider Portal Phase 21), already wired to real triggers
    #     (notify_riders_of_new_delivery, the cancellation branch of
    #     notify_order_status_change) and already tested — renamed
    #     duplicates would split one concept across two enum values with
    #     two different sets of callers to keep in sync.
    #   - ADMIN_ALERT: a single generic catch-all would be *less* precise
    #     than the granular set of admin-facing types this catalog already
    #     has (NEW_RESTAURANT_REGISTERED, NEW_RIDER_REGISTERED,
    #     DOCUMENT_SUBMITTED, ORDER_ISSUE, PAYMENT_FAILURE,
    #     COD_SETTLEMENT_DUE, SYSTEM_ALERT) — adding it would invite a
    #     future caller to reach for the vague type instead of picking (or
    #     adding, following this same pattern) the specific one.


class NotificationChannel(str, enum.Enum):
    """Notifications & Communication System Phase 3 — Notification Domain
    Model. IN_APP is true of every row unconditionally (the row's own
    existence *is* the in-app delivery — there is no separate "in-app
    send" step that can fail); PUSH means a push attempt was actually
    made for this notification, distinct from a recipient with no
    registered device at all, who only ever gets IN_APP."""

    IN_APP = "in_app"
    PUSH = "push"


class NotificationStatus(str, enum.Enum):
    """Phase 3. Deliberately narrow for now — this only tracks whether the
    (synchronous, best-effort) push attempt reached the provider at all,
    not the provider's own per-message delivery outcome (Expo's response
    is currently only inspected for DeviceNotRegistered, to prune stale
    tokens — see push_notifications.py). Real per-notification
    retry/failure tracking is Phase 31's explicitly-scoped job; wiring
    these three values now would mean either leaving them permanently
    hollow or redesigning the push layer's return contract ahead of the
    phase that's actually meant to do that design work.

    PENDING never currently appears on a row created via the synchronous
    call sites (by the time db.commit() returns, the attempt has already
    resolved to SENT or FAILED) — it exists for the one already-real
    asynchronous path (notify_admins' BackgroundTasks variant), where the
    row is committed before the deferred push attempt runs at all."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_is_read", "user_id", "is_read"),
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_type", "type"),
        Index("ix_notifications_status", "status"),
        # Notification History/Retention (Phase 34) — purge_old_notifications'
        # own access pattern: a global (not per-user) "is_read = X AND
        # created_at < cutoff" sweep. The existing (user_id, is_read)
        # index doesn't help a query with no user_id filter at all.
        Index("ix_notifications_is_read_created_at", "is_read", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Notifications & Communication System Phase 3 — a snapshot of the recipient's role at the moment this
    # notification was created, the same "captured once, never re-derived"
    # discipline this codebase already applies to Order's customer/
    # restaurant fields — not a live join to users.role, so a role change
    # (rare, but not impossible) never rewrites a notification's own
    # historical context. Always statically known at every existing call
    # site (an order's own customer is always role=CUSTOMER, an admin
    # broadcast's recipients are always role=ADMIN, etc.) — never requires
    # an extra query to populate.
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Notifications & Communication System Phase 3 — the same structured payload already being handed to the
    # push provider as its `data` field (see push_notifications.py),
    # additionally persisted here so a client re-fetching notification
    # *history* (GET /notifications) has the same deep-link context a live
    # push already carries — today that history-read path only ever gets
    # order_id. Generic JSON (not JSONB): this backend's whole test suite
    # runs against SQLite, which has no JSONB type — a Postgres-only
    # column would break every test touching this table.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Notifications & Communication System Phase 3 — see NotificationChannel/NotificationStatus's own
    # docstrings for what these do and don't track yet.
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=NotificationChannel.IN_APP,
        server_default=NotificationChannel.IN_APP.value,
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
        nullable=False,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Notifications & Communication System Phase 3 — set the moment is_read flips true (mark_notification_read/
    # mark_all_notifications_read), never backfilled or re-derived; NULL
    # means genuinely never read, not "read but the timestamp is unknown."
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Notifications & Communication System Phase 3 — populated only for the synchronous push path today (see
    # NotificationStatus's own docstring); NULL on a row whose channel
    # never included a push attempt at all, or whose async dispatch
    # (notify_admins' BackgroundTasks variant) hasn't resolved yet.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
