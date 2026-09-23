from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.push_token import PushToken
from app.models.user import User, UserRole
from app.services.push_notifications import send_push_to_user, send_push_to_users, send_push_to_users_in_background


def _notifications_enabled(db: Session) -> bool:
    """Admin Portal Phase 22's platform-wide notification kill switch.
    Imported lazily (not at module scope) to avoid a circular import:
    admin_settings.py doesn't import this module, but keeping the import
    inside the function keeps that guarantee explicit rather than relying
    on import order."""
    from app.services.admin_settings import get_platform_settings

    return get_platform_settings(db).notifications_enabled


def upsert_push_token(db: Session, user_id: UUID, token: str, platform: str = "expo") -> PushToken:
    existing = db.scalar(select(PushToken).where(PushToken.user_id == user_id, PushToken.token == token))
    if existing:
        existing.platform = platform
        db.commit()
        db.refresh(existing)
        return existing

    push_token = PushToken(user_id=user_id, token=token, platform=platform)
    db.add(push_token)
    db.commit()
    db.refresh(push_token)
    return push_token


def delete_push_token(db: Session, user_id: UUID, token: str) -> None:
    """Called on logout — stops pushes to this one device without touching
    the user's other logged-in devices' tokens."""
    db.query(PushToken).filter(PushToken.user_id == user_id, PushToken.token == token).delete()
    db.commit()


# Maps an order status transition to the notification it should raise for the
# customer. PLACED has no entry here — it's not reached via
# transition_order_status() at all (create_order sets it directly on
# construction), so it's raised separately, right where the order is
# created (see notify_order_placed below).
_ORDER_STATUS_NOTIFICATIONS: dict[OrderStatus, tuple[NotificationType, str, str]] = {
    OrderStatus.CONFIRMED: (
        NotificationType.ORDER_CONFIRMED,
        "Order confirmed",
        "Your order {order_number} has been confirmed by {restaurant_name}.",
    ),
    OrderStatus.PICKED_UP: (
        NotificationType.ORDER_PICKED_UP,
        "Order picked up",
        "Your order {order_number} has been picked up and is on its way to you soon.",
    ),
    OrderStatus.PREPARING: (
        NotificationType.ORDER_PREPARING,
        "Preparing your order",
        "{restaurant_name} is preparing your order {order_number}.",
    ),
    OrderStatus.READY_FOR_PICKUP: (
        NotificationType.ORDER_READY,
        "Order ready",
        "Your order {order_number} is ready for pickup.",
    ),
    OrderStatus.RIDER_ASSIGNED: (
        NotificationType.RIDER_ASSIGNED,
        "Rider assigned",
        "A delivery partner has been assigned to your order {order_number}.",
    ),
    OrderStatus.OUT_FOR_DELIVERY: (
        NotificationType.ORDER_OUT_FOR_DELIVERY,
        "Out for delivery",
        "Your order {order_number} is on its way.",
    ),
    OrderStatus.DELIVERED: (
        NotificationType.ORDER_DELIVERED,
        "Delivered",
        "Your order {order_number} has been delivered. Enjoy!",
    ),
    OrderStatus.CANCELLED: (
        NotificationType.ORDER_CANCELLED,
        "Order cancelled",
        "Your order {order_number} has been cancelled.",
    ),
    OrderStatus.REJECTED: (
        NotificationType.ORDER_REJECTED,
        "Order rejected",
        "{restaurant_name} was unable to accept your order {order_number}.",
    ),
}


def notify_order_placed(db: Session, order: Order) -> None:
    """PLACED never goes through transition_order_status() (create_order
    sets it directly on construction, since there's no prior status to
    transition *from*), so it needs its own explicit call — made once,
    right after the order is committed in create_order()."""
    if not _notifications_enabled(db):
        return
    title = "Order placed"
    body = f"We've received your order {order.order_number}. {order.restaurant_name or 'The restaurant'} will confirm it shortly."
    db.add(
        Notification(
            user_id=order.user_id,
            type=NotificationType.ORDER_PLACED,
            title=title,
            body=body,
            order_id=order.id,
        )
    )
    send_push_to_user(
        db,
        order.user_id,
        title,
        body,
        data={"type": "order_status", "order_id": str(order.id), "status": OrderStatus.PLACED.value},
    )


def notify_order_status_change(db: Session, order: Order, new_status: OrderStatus) -> None:
    if not _notifications_enabled(db):
        return
    mapping = _ORDER_STATUS_NOTIFICATIONS.get(new_status)
    if mapping:
        notification_type, title, body_template = mapping
        body = body_template.format(
            order_number=order.order_number,
            restaurant_name=order.restaurant_name or "the restaurant",
        )
        db.add(
            Notification(
                user_id=order.user_id,
                type=notification_type,
                title=title,
                body=body,
                order_id=order.id,
            )
        )
        # Best-effort push alongside the in-app row — deep-links the tap
        # straight to this order's tracking/detail screen on the client.
        send_push_to_user(
            db,
            order.user_id,
            title,
            body,
            data={"type": "order_status", "order_id": str(order.id), "status": new_status.value},
        )

    # A rider who already had this delivery assigned needs to hear about a
    # cancellation too — separately from the customer's own ORDER_CANCELLED
    # notification above, and only when a rider was actually involved (an
    # order cancelled before ever being assigned has no rider to tell).
    if new_status == OrderStatus.CANCELLED and order.rider_id is not None:
        rider_title = "Delivery cancelled"
        rider_body = f"Order {order.order_number} has been cancelled and is no longer awaiting delivery."
        db.add(
            Notification(
                user_id=order.rider_id,
                type=NotificationType.DELIVERY_CANCELLED,
                title=rider_title,
                body=rider_body,
                order_id=order.id,
            )
        )
        send_push_to_user(
            db,
            order.rider_id,
            rider_title,
            rider_body,
            data={"type": "delivery_cancelled", "order_id": str(order.id)},
        )


def notify_riders_of_new_delivery(db: Session, order: Order) -> None:
    """Broadcasts to every currently-online, approved rider the moment an
    order becomes READY_FOR_PICKUP — the same eligibility this order would
    need to actually show up in that rider's GET /rider/deliveries/available
    list (Phase 9), so nobody gets pinged for a delivery they couldn't see
    or accept anyway."""
    if not _notifications_enabled(db):
        return
    eligible_rider_ids = list(
        db.scalars(
            select(DeliveryPartner.user_id).where(
                DeliveryPartner.is_online.is_(True), DeliveryPartner.approval_status == ApprovalStatus.APPROVED
            )
        )
    )
    if not eligible_rider_ids:
        return

    title = "New delivery available"
    body = f"A new delivery from {order.restaurant_name or 'a restaurant'} is ready for pickup."
    for rider_id in eligible_rider_ids:
        db.add(
            Notification(
                user_id=rider_id, type=NotificationType.NEW_DELIVERY, title=title, body=body, order_id=order.id
            )
        )
    send_push_to_users(db, eligible_rider_ids, title, body, data={"type": "new_delivery", "order_id": str(order.id)})


def notify_customer_payment_failed(db: Session, *, user_id: UUID, order_id: UUID, order_number: str) -> None:
    """Notification Event Integration (Phase 20) — the customer's own side
    of a failed online-payment verification (see verify_payment in
    services/payments.py), which previously only alerted admins. Reuses
    the PAYMENT_UPDATE type, defined but never actually raised until now —
    dormant the same way the online-payment flow itself is dormant (see
    that flow's own notes: payment_method is locked to "cod" at order
    creation today), but correctly wired for whenever it becomes reachable."""
    if not _notifications_enabled(db):
        return
    title = "Payment failed"
    body = f"We couldn't verify your payment for order {order_number}. Please try again."
    db.add(
        Notification(
            user_id=user_id, type=NotificationType.PAYMENT_UPDATE, title=title, body=body, order_id=order_id,
        )
    )
    send_push_to_user(
        db, user_id, title, body, data={"type": "payment_failed", "order_id": str(order_id)},
    )


def notify_admins(
    db: Session, notification_type: NotificationType, title: str, body: str, *,
    order_id: UUID | None = None, background_tasks: BackgroundTasks | None = None,
) -> int:
    """Admin Portal Phase 20 — an operational alert delivered to every
    active admin user, the same one-row-per-recipient broadcast shape
    broadcast_promotion already uses for customers. Deliberately does NOT
    call db.commit() itself: every caller triggers this as a side effect of
    some other write (a new restaurant, a failed payment, an order
    cancellation, ...) that has its own commit at the end, so the alert is
    persisted atomically together with the event that caused it rather
    than as a separate, independently-committable step.

    Performance & Reliability (Phase 39) — the actual push delivery (a
    real network call to Expo, up to PUSH_REQUEST_TIMEOUT_SECONDS) is the
    one part of this function that doesn't need to happen before the
    caller's own response — the Notification rows above are what the
    in-app bell actually reads, and are still written synchronously,
    atomically with the caller's own commit, exactly as before. When a
    caller hands in `background_tasks` (currently: the webhook handler,
    where a slow Expo response must never delay Razorpay's own ack), the
    push send is deferred to run after the response instead of blocking
    it; callers that don't pass it keep the prior synchronous behavior
    unchanged."""
    if not _notifications_enabled(db):
        return 0
    admin_ids = list(db.scalars(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))))
    for admin_id in admin_ids:
        db.add(Notification(user_id=admin_id, type=notification_type, title=title, body=body, order_id=order_id))
    if admin_ids:
        if background_tasks is not None:
            background_tasks.add_task(
                send_push_to_users_in_background, admin_ids, title, body, {"type": notification_type.value}
            )
        else:
            send_push_to_users(db, admin_ids, title, body, data={"type": notification_type.value})
    return len(admin_ids)


def broadcast_promotion(db: Session, title: str, body: str) -> int:
    """Sends a promotional push + in-app notification to every active customer.

    Returns how many customers actually had a device to notify (not the total
    customer count) — an admin sending a promo wants to know it reached
    someone, not just that the DB write succeeded.
    """
    if not _notifications_enabled(db):
        return 0
    customer_ids = list(
        db.scalars(select(User.id).where(User.role == UserRole.CUSTOMER, User.is_active.is_(True)))
    )
    for user_id in customer_ids:
        db.add(Notification(user_id=user_id, type=NotificationType.PROMOTION, title=title, body=body))
    notified = send_push_to_users(db, customer_ids, title, body, data={"type": "promotion"})
    db.commit()
    return notified


_MAX_NOTIFICATIONS_RETURNED = 100


def list_notifications(db: Session, user_id: UUID) -> list[Notification]:
    # Phase 30: shared by both the Customer and Rider portals — neither has
    # ever paginated this, so a long-tenured account's list would otherwise
    # grow unbounded on every single call. Capped at the most recent 100
    # rather than adding pagination params to a function both portals'
    # existing screens call with no such params today.
    return list(
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(_MAX_NOTIFICATIONS_RETURNED)
        .all()
    )


def mark_notification_read(db: Session, user_id: UUID, notification_id: UUID) -> Notification:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


def mark_all_notifications_read(db: Session, user_id: UUID) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return updated
