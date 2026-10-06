import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.observability import log_event
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.notification_preference import NotificationPreference
from app.models.order import Order, OrderStatus
from app.models.payment import Payment
from app.models.push_token import PushToken
from app.models.refund import Refund
from app.models.rider_document import DocumentVerificationStatus, RiderDocument
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.notification import NotificationDeepLinkCategory, build_notification_data
from app.services.push_notifications import send_push_to_user, send_push_to_users, send_push_to_users_in_background

logger = logging.getLogger(__name__)


@contextmanager
def _notification_failure_boundary(db: Session, **event_fields):
    """Notifications & Communication System Phase 7 — Notification
    Service, "handle failure."

    Every notify_* function's actual DB-write-plus-dispatch work runs
    inside this. It's a SAVEPOINT (Session.begin_nested()), not a bare
    try/except, because several callers — transition_order_status, in
    particular — invoke a notify_* function *before* their own
    db.commit(): a bare try/except would catch the exception, but the
    session would still carry whatever partial/broken state the failed
    notification work left behind, corrupting the caller's own
    still-uncommitted business changes the next time anyone touches that
    session. Rolling back to a savepoint undoes only the notification's
    own work, leaving everything the caller already did earlier in the
    same transaction completely intact. This is what actually makes
    Rule 4 ("notification failure must not break business operations")
    true at the database level, not just true by convention.

    Observability (Phase 43) — "notification_created" on success,
    "notification_failed" (renamed from this file's own earlier
    "notification_error") on an unhandled exception inside the body —
    the DB-write-plus-dispatch crashing outright (a bug, the database
    itself being unavailable), distinct from push_notifications.py's own
    "notification_failed" for a provider-confirmed per-message rejection
    (which never raises here at all, by design — the two can't overlap
    in practice). event_fields (notification_type, order_id) are already
    exactly what every call site already passes for the failure log; the
    same fields describe the success case too."""
    try:
        with db.begin_nested():
            yield
        log_event(logger, "notification_created", **event_fields)
    except Exception as exc:
        log_event(logger, "notification_failed", reason=type(exc).__name__, **event_fields)
        logger.warning("Notification delivery failed", exc_info=True)


def _notifications_enabled(db: Session) -> bool:
    """Admin Portal Phase 22's platform-wide notification kill switch.
    Imported lazily (not at module scope) to avoid a circular import:
    admin_settings.py doesn't import this module, but keeping the import
    inside the function keeps that guarantee explicit rather than relying
    on import order."""
    from app.services.admin_settings import get_platform_settings

    return get_platform_settings(db).notifications_enabled


# Notification Preferences (Phase 24) — every NotificationType a real
# person (never an admin-only operational alert) can receive, mapped to
# exactly one of the five preference categories. A type with no entry
# here is never gated by preference at all — that's deliberate, not an
# omission: every type left out (NEW_RESTAURANT_REGISTERED,
# NEW_RIDER_REGISTERED, DOCUMENT_SUBMITTED, ORDER_ISSUE, PAYMENT_FAILURE,
# SYSTEM_ALERT) is exclusively used by notify_admins — see this
# codebase's own _ADMIN_NOTIFICATION_TYPES — and an admin's operational
# alerts are a job-function responsibility, not a personal preference
# they should be able to silence.
#
# ACCOUNT_APPROVED/ACCOUNT_SUSPENDED are also deliberately left out,
# despite being very much "personal" — they gate whether a rider can
# even go online and work at all, the clearest case of "transactional
# notifications should remain enabled where necessary for service
# operation." A system_notifications toggle governs purely informational
# updates (a document review outcome, a general platform notice); it
# must never be able to silence whether someone finds out they can no
# longer work.
_NOTIFICATION_CATEGORY: dict[NotificationType, str] = {
    NotificationType.ORDER_PLACED: "order_updates",
    NotificationType.ORDER_CONFIRMED: "order_updates",
    NotificationType.ORDER_PREPARING: "order_updates",
    NotificationType.ORDER_READY: "order_updates",
    NotificationType.ORDER_CANCELLED: "order_updates",
    NotificationType.ORDER_REJECTED: "order_updates",
    NotificationType.RESTAURANT_NEW_ORDER: "order_updates",
    NotificationType.RESTAURANT_ORDER_CANCELLED: "order_updates",
    NotificationType.RIDER_ASSIGNED: "delivery_updates",
    NotificationType.ORDER_PICKED_UP: "delivery_updates",
    NotificationType.ORDER_OUT_FOR_DELIVERY: "delivery_updates",
    NotificationType.RIDER_APPROACHING: "delivery_updates",
    NotificationType.ORDER_DELIVERED: "delivery_updates",
    NotificationType.NEW_DELIVERY: "delivery_updates",
    NotificationType.DELIVERY_CANCELLED: "delivery_updates",
    NotificationType.DELIVERY_UPDATED: "delivery_updates",
    NotificationType.PAYMENT_UPDATE: "payment_updates",
    NotificationType.PAYMENT_SUCCESS: "payment_updates",
    NotificationType.REFUND_INITIATED: "payment_updates",
    NotificationType.REFUND_COMPLETED: "payment_updates",
    NotificationType.COD_PENDING: "payment_updates",
    NotificationType.COD_COLLECTED: "payment_updates",
    NotificationType.COD_SETTLEMENT_DUE: "payment_updates",
    NotificationType.EARNING_UPDATE: "payment_updates",
    NotificationType.PROMOTION: "promotions",
    NotificationType.SYSTEM: "system_notifications",
    NotificationType.DOCUMENT_APPROVED: "system_notifications",
    NotificationType.DOCUMENT_REJECTED: "system_notifications",
}


def get_or_create_notification_preference(db: Session, user_id: UUID) -> NotificationPreference:
    """Lazily materializes a preference row the first time anything
    actually needs one — the same pattern DeliveryPartner's own
    get_or_create already established — so every account, including one
    created long before this table existed, always has a well-defined
    set of preferences without a backfill migration. Only ever flushes,
    never commits: this is called both from read paths that want to
    commit themselves (the GET/PUT preference endpoints) and from deep
    inside a notify_* function's own ambient transaction, where an
    unexpected commit here would prematurely commit a caller's own
    still-in-progress work."""
    preference = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if preference is not None:
        return preference
    preference = NotificationPreference(user_id=user_id)
    db.add(preference)
    try:
        db.flush()
    except IntegrityError:
        # Two near-simultaneous first-touches for the same user both saw
        # no existing row — uq_notification_preferences_user_id lets
        # exactly one insert win; fall back to the winner's own row,
        # mirroring this codebase's own established check-then-insert
        # recovery pattern (e.g. create_order's cart claim).
        db.rollback()
        preference = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    return preference


def update_notification_preference(
    db: Session, user_id: UUID, updates: dict[str, bool | None]
) -> NotificationPreference:
    preference = get_or_create_notification_preference(db, user_id)
    for field, value in updates.items():
        if value is not None:
            setattr(preference, field, value)
    db.commit()
    db.refresh(preference)
    return preference


def _user_wants(db: Session, user_id: UUID, notification_type: NotificationType) -> bool:
    category = _NOTIFICATION_CATEGORY.get(notification_type)
    if category is None:
        return True
    preference = get_or_create_notification_preference(db, user_id)
    return bool(getattr(preference, category))


def _filter_users_wanting(db: Session, user_ids: list[UUID], notification_type: NotificationType) -> list[UUID]:
    """The broadcast counterpart to _user_wants — for
    notify_riders_of_new_delivery/broadcast_promotion, which address many
    recipients at once rather than one. A recipient with no preference
    row yet is always included (the same "absence means defaults apply"
    rule _user_wants' own get_or_create would otherwise apply one row at
    a time) — only an existing row that explicitly opted out excludes
    someone, so this never needs to materialize a row for every single
    broadcast recipient just to check."""
    category = _NOTIFICATION_CATEGORY.get(notification_type)
    if category is None or not user_ids:
        return user_ids
    preferences = db.scalars(
        select(NotificationPreference).where(NotificationPreference.user_id.in_(user_ids))
    ).all()
    opted_out = {p.user_id for p in preferences if not getattr(p, category)}
    return [user_id for user_id in user_ids if user_id not in opted_out]


def upsert_push_token(
    db: Session, user_id: UUID, token: str, platform: str = "expo", device_identifier: str | None = None
) -> PushToken:
    """Notifications & Communication System Phase 14 — Push Token Domain.

    Never assume one user has at most one device: this only ever adds or
    updates a single row, it never touches this user's other rows. Which
    row it updates depends on what the caller can prove is the *same
    device* as before:

    - device_identifier given and already on file for this user -> that
      row is the same physical device re-registering, most often because
      its push token itself just rotated (both iOS and Android do this
      periodically, not only on reinstall); its token is updated in
      place rather than leaving the old, now-dead token behind as an
      orphaned row nothing will ever clean up until Expo happens to
      bounce a push off it.
    - otherwise, falls back to this table's original (user_id, token)
      match — the whole story for a client that doesn't send a
      device_identifier yet, preserving that behavior unchanged.
    - neither matches -> a genuinely new device for this user; a new row
      is added alongside whatever rows this user already has.

    Push Token Registration (Phase 15) — "duplicate token." The exact same
    token string can legitimately end up active under two different
    user_id rows: a shared/reused physical device where a second person
    signs in without the app ever requesting a fresh push token first
    (nothing forces a rotation on login/logout). Without this, both
    accounts would keep receiving each other's pushes on that one device
    indefinitely. A token can only ever be honestly "reachable" for
    whoever is currently authenticated with it, so registering it for
    this user deactivates it everywhere else first — the same
    single-owner guarantee a login session already gives an access token,
    applied here to a push token.
    """
    db.execute(
        update(PushToken)
        .where(PushToken.token == token, PushToken.user_id != user_id, PushToken.is_active.is_(True))
        .values(is_active=False)
    )

    existing = None
    if device_identifier:
        existing = db.scalar(
            select(PushToken).where(PushToken.user_id == user_id, PushToken.device_identifier == device_identifier)
        )
    if existing is None:
        existing = db.scalar(select(PushToken).where(PushToken.user_id == user_id, PushToken.token == token))

    now = datetime.now(UTC)
    if existing:
        existing.token = token
        existing.platform = platform
        if device_identifier:
            existing.device_identifier = device_identifier
        existing.is_active = True
        existing.last_seen_at = now
        db.commit()
        db.refresh(existing)
        # Observability (Phase 43) — never the raw token string itself,
        # only the row's own id and platform.
        log_event(logger, "push_token_registered", push_token_id=existing.id, platform=platform, renewed=True)
        return existing

    push_token = PushToken(
        user_id=user_id, token=token, platform=platform, device_identifier=device_identifier,
        is_active=True, last_seen_at=now,
    )
    db.add(push_token)
    db.commit()
    db.refresh(push_token)
    log_event(logger, "push_token_registered", push_token_id=push_token.id, platform=platform, renewed=False)
    return push_token


def delete_push_token(db: Session, user_id: UUID, token: str) -> None:
    """Called on logout — deactivates this one device's row without
    touching the user's other logged-in devices' rows, and without
    discarding it outright: a soft deactivation (is_active=False), not a
    delete. A re-login from the same physical device is a normal, common
    event (unlike Expo itself declaring a token permanently dead — see
    push_notifications.py's own stale-token cleanup, which still deletes
    outright), and preserving the row lets a future re-registration with
    the same device_identifier revive and reuse it via upsert_push_token
    above rather than accumulating a dead duplicate."""
    existing = db.scalar(select(PushToken).where(PushToken.user_id == user_id, PushToken.token == token))
    if existing:
        existing.is_active = False
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
    if not _notifications_enabled(db) or not _user_wants(db, order.user_id, NotificationType.ORDER_PLACED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.ORDER_PLACED.value, order_id=order.id):
        title = "Order placed"
        body = f"We've received your order {order.order_number}. {order.restaurant_name or 'The restaurant'} will confirm it shortly."
        data = build_notification_data(NotificationDeepLinkCategory.ORDER_STATUS, order_id=order.id, status=OrderStatus.PLACED.value)
        db.add(
            Notification(
                user_id=order.user_id,
                role=UserRole.CUSTOMER,
                type=NotificationType.ORDER_PLACED,
                title=title,
                body=body,
                data=data,
                order_id=order.id,
            )
        )
        send_push_to_user(db, order.user_id, title, body, data=data)


def notify_order_status_change(db: Session, order: Order, new_status: OrderStatus) -> None:
    if not _notifications_enabled(db):
        return
    mapping = _ORDER_STATUS_NOTIFICATIONS.get(new_status)
    if mapping and _user_wants(db, order.user_id, mapping[0]):
        notification_type, title, body_template = mapping
        with _notification_failure_boundary(db, notification_type=notification_type.value, order_id=order.id):
            body = body_template.format(
                order_number=order.order_number,
                restaurant_name=order.restaurant_name or "the restaurant",
            )
            data = build_notification_data(NotificationDeepLinkCategory.ORDER_STATUS, order_id=order.id, status=new_status.value)
            db.add(
                Notification(
                    user_id=order.user_id,
                    role=UserRole.CUSTOMER,
                    type=notification_type,
                    title=title,
                    body=body,
                    data=data,
                    order_id=order.id,
                )
            )
            # Best-effort push alongside the in-app row — deep-links the tap
            # straight to this order's tracking/detail screen on the client.
            send_push_to_user(db, order.user_id, title, body, data=data)

    # A rider who already had this delivery assigned needs to hear about a
    # cancellation too — separately from the customer's own ORDER_CANCELLED
    # notification above, and only when a rider was actually involved (an
    # order cancelled before ever being assigned has no rider to tell).
    # A separate failure boundary from the customer notification above —
    # one failing must never prevent the other from being attempted.
    if (
        new_status == OrderStatus.CANCELLED
        and order.rider_id is not None
        and _user_wants(db, order.rider_id, NotificationType.DELIVERY_CANCELLED)
    ):
        with _notification_failure_boundary(db, notification_type=NotificationType.DELIVERY_CANCELLED.value, order_id=order.id):
            rider_title = "Delivery cancelled"
            rider_body = f"Order {order.order_number} has been cancelled and is no longer awaiting delivery."
            rider_data = build_notification_data(NotificationDeepLinkCategory.DELIVERY_CANCELLED, order_id=order.id)
            db.add(
                Notification(
                    user_id=order.rider_id,
                    role=UserRole.RIDER,
                    type=NotificationType.DELIVERY_CANCELLED,
                    title=rider_title,
                    body=rider_body,
                    data=rider_data,
                    order_id=order.id,
                )
            )
            send_push_to_user(db, order.rider_id, rider_title, rider_body, data=rider_data)

    # Notifications & Communication System Phase 12 — Restaurant Owner
    # Notifications. Hooked into this same choke point (not a new call
    # site at every caller) so it fires regardless of which path actually
    # triggered the transition — accept_delivery, assign_rider_to_order,
    # or the admin-direct-assign flow all converge on
    # transition_order_status, which is the only thing that calls this
    # function at all.
    if new_status == OrderStatus.CANCELLED:
        notify_restaurant_order_cancelled(db, order)
    if new_status == OrderStatus.RIDER_ASSIGNED:
        notify_restaurant_rider_assigned(db, order)
    if new_status == OrderStatus.DELIVERED:
        notify_restaurant_delivery_completed(db, order)

    # COD Notifications (Phase 22) — "collection required," the moment a
    # COD rider is actually about to hand the order over, not earlier.
    if new_status == OrderStatus.OUT_FOR_DELIVERY and order.payment_method == "cod" and not order.is_paid and order.rider_id is not None:
        rider = db.get(User, order.rider_id)
        if rider is not None:
            notify_rider_cod_collection_required(db, rider, order)


def notify_rider_new_assignment(db: Session, rider: User, order: Order) -> None:
    """Rider Delivery Notifications (Phase 20) — "new assignment." Distinct
    from notify_riders_of_new_delivery (a broadcast to every eligible
    online rider, inviting them to self-accept) — this is the personal
    notification for the one case a rider ends up responsible for a
    delivery without ever choosing it themselves: an admin directly
    assigning them to an order (admin_assign_rider_to_order ->
    assign_rider_to_order). The self-service accept_delivery path
    deliberately raises none of this — Phase 11's own "a rider's own
    synchronous action already has its own immediate UI feedback" rule;
    accept_delivery never calls assign_rider_to_order at all, so this can
    never double-fire for it. Reuses NEW_DELIVERY — the same underlying
    "you have a delivery to look at" concept; a distinct title/body is
    what actually tells the two apart."""
    if not _notifications_enabled(db) or not _user_wants(db, rider.id, NotificationType.NEW_DELIVERY):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.NEW_DELIVERY.value, order_id=order.id):
        title = "New delivery assigned"
        body = f"You've been assigned to deliver order {order.order_number}."
        data = build_notification_data(NotificationDeepLinkCategory.NEW_DELIVERY, order_id=order.id)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.NEW_DELIVERY,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def maybe_notify_rider_approaching(db: Session, order: Order, rider_latitude: Decimal, rider_longitude: Decimal) -> None:
    """Live Rider Tracking Phase 34 — Notification Integration.

    "Rider is approaching" is a proximity event, not a status-change
    event, so it can't reuse _ORDER_STATUS_NOTIFICATIONS/
    notify_order_status_change — it's evaluated on every accepted rider
    location update instead (see rider_location.py::update_rider_location).
    Two things keep this from becoming "a notification for every GPS
    update," which this phase explicitly forbids:

    - Only evaluated while the order is OUT_FOR_DELIVERY (the leg where
      the rider is actually travelling toward the customer, not the
      restaurant) and only once the rider is within
      RIDER_APPROACHING_DISTANCE_KM in a straight line — most updates
      simply don't qualify.
    - Once a RIDER_APPROACHING notification exists for this order, every
      later call is a no-op — checked against the Notification table
      itself (durable, survives a server restart) rather than an
      in-process flag, so this can never fire twice for the same order
      even across a restart mid-delivery."""
    if order.status != OrderStatus.OUT_FOR_DELIVERY:
        return
    if order.latitude is None or order.longitude is None:
        return
    if not _notifications_enabled(db) or not _user_wants(db, order.user_id, NotificationType.RIDER_APPROACHING):
        return

    from app.services import location_service

    distance_km = location_service.distance_km(rider_latitude, rider_longitude, order.latitude, order.longitude)
    if distance_km > settings.RIDER_APPROACHING_DISTANCE_KM:
        return

    already_notified = db.scalar(
        select(Notification.id).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING)
    )
    if already_notified is not None:
        return

    with _notification_failure_boundary(db, notification_type=NotificationType.RIDER_APPROACHING.value, order_id=order.id):
        title = "Your rider is almost there"
        body = f"Your delivery partner is close by with order {order.order_number}."
        data = build_notification_data(NotificationDeepLinkCategory.RIDER_APPROACHING, order_id=order.id)
        db.add(
            Notification(
                user_id=order.user_id,
                role=UserRole.CUSTOMER,
                type=NotificationType.RIDER_APPROACHING,
                title=title,
                body=body,
                data=data,
                order_id=order.id,
            )
        )
        send_push_to_user(db, order.user_id, title, body, data=data)
    db.commit()


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
    # Notification Preferences (Phase 24) — a rider who turned off
    # delivery_updates still shows up in list_available_deliveries (this
    # is a broadcast *invitation*, not a status update about a delivery
    # they already have), they just don't get pinged about new ones.
    eligible_rider_ids = _filter_users_wanting(db, eligible_rider_ids, NotificationType.NEW_DELIVERY)
    if not eligible_rider_ids:
        return

    with _notification_failure_boundary(db, notification_type=NotificationType.NEW_DELIVERY.value, order_id=order.id):
        title = "New delivery available"
        body = f"A new delivery from {order.restaurant_name or 'a restaurant'} is ready for pickup."
        data = build_notification_data(NotificationDeepLinkCategory.NEW_DELIVERY, order_id=order.id)
        for rider_id in eligible_rider_ids:
            db.add(
                Notification(
                    user_id=rider_id, role=UserRole.RIDER, type=NotificationType.NEW_DELIVERY,
                    title=title, body=body, data=data, order_id=order.id,
                )
            )
        send_push_to_users(db, eligible_rider_ids, title, body, data=data)


def notify_customer_payment_failed(db: Session, *, user_id: UUID, order_id: UUID, order_number: str) -> None:
    """Notification Event Integration (Phase 20) — the customer's own side
    of a failed online-payment verification (see verify_payment in
    services/payments.py), which previously only alerted admins. Reuses
    the PAYMENT_UPDATE type, defined but never actually raised until now —
    dormant the same way the online-payment flow itself is dormant (see
    that flow's own notes: payment_method is locked to "cod" at order
    creation today), but correctly wired for whenever it becomes reachable."""
    if not _notifications_enabled(db) or not _user_wants(db, user_id, NotificationType.PAYMENT_UPDATE):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.PAYMENT_UPDATE.value, order_id=order_id):
        title = "Payment failed"
        body = f"We couldn't verify your payment for order {order_number}. Please try again."
        data = build_notification_data(NotificationDeepLinkCategory.PAYMENT_FAILED, order_id=order_id)
        db.add(
            Notification(
                user_id=user_id, role=UserRole.CUSTOMER, type=NotificationType.PAYMENT_UPDATE,
                title=title, body=body, data=data, order_id=order_id,
            )
        )
        send_push_to_user(db, user_id, title, body, data=data)


# Notifications & Communication System Phase 7 — Notification Service,
# "validate notification type." notify_admins (unlike every other notify_*
# function, which hardcodes its own single NotificationType) accepts the
# type as a caller-supplied parameter — a real place a bug could pass the
# wrong one (e.g. a customer-facing type reaching an admin's notification
# feed). Checked eagerly, before the failure boundary below, so a wrong
# type raises immediately and loudly (a programmer error, caught in
# development/tests) rather than being silently swallowed the way a
# genuine external delivery failure is meant to be.
_ADMIN_NOTIFICATION_TYPES = frozenset(
    {
        NotificationType.NEW_RESTAURANT_REGISTERED,
        NotificationType.NEW_RIDER_REGISTERED,
        NotificationType.DOCUMENT_SUBMITTED,
        NotificationType.ORDER_ISSUE,
        NotificationType.PAYMENT_FAILURE,
        NotificationType.COD_SETTLEMENT_DUE,
        NotificationType.SYSTEM_ALERT,
    }
)

# Rate Limiting / Anti-Spam (Phase 33) — a documented, adjustable
# business rule, the same pattern as COD_SETTLEMENT_DUE_THRESHOLD/
# _PAYMENT_EXPIRY_WINDOW elsewhere in this codebase, not derived from
# anything.
_ADMIN_ALERT_AGGREGATION_WINDOW = timedelta(minutes=5)


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
    real network call through the configured PushProvider, see
    app/services/push/) is the one part of this function that doesn't
    need to happen before the
    caller's own response — the Notification rows above are what the
    in-app bell actually reads, and are still written synchronously,
    atomically with the caller's own commit, exactly as before. When a
    caller hands in `background_tasks` (currently: the webhook handler,
    where a slow Expo response must never delay Razorpay's own ack), the
    push send is deferred to run after the response instead of blocking
    it; callers that don't pass it keep the prior synchronous behavior
    unchanged."""
    if notification_type not in _ADMIN_NOTIFICATION_TYPES:
        raise ValueError(f"{notification_type.value!r} is not one of this codebase's admin-facing notification types")
    if not _notifications_enabled(db):
        return 0
    admin_ids = list(db.scalars(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))))
    if not admin_ids:
        return 0

    notified_count = 0
    with _notification_failure_boundary(db, notification_type=notification_type.value, order_id=order_id):
        data = {"type": notification_type.value}
        if order_id is not None:
            data["order_id"] = str(order_id)

        # Rate Limiting / Anti-Spam (Phase 33) — "repeated admin alerts."
        # An admin who already has a recent, still-unread alert of this
        # exact type gets that same row refreshed (an occurrence count
        # folded into its body) and no second push, rather than a brand
        # new row and a brand new push for every single occurrence — a
        # burst of, say, 50 payment failures during a provider outage
        # must not mean 50 separate pushes landing on every admin's
        # phone in the same few minutes. Scoped to is_read=False and a
        # short window: once an admin actually reads it, or once enough
        # quiet time has passed, a genuinely new occurrence earns its
        # own fresh notification again. Deliberately never applied to
        # any customer/rider/restaurant notification — each of those is
        # about a different person's own specific order and must never
        # be suppressed just because many happened at once.
        cutoff = datetime.now(UTC) - _ADMIN_ALERT_AGGREGATION_WINDOW
        # Performance Testing (Phase 41) — one bulk query for every admin
        # at once, not one SELECT per admin in the loop below. Ordered by
        # recency so the first row seen per admin_id in the loop is
        # always that admin's own most recent matching alert — the same
        # row .limit(1) would have picked per-admin, now picked in
        # memory instead of with N separate round trips.
        recent_rows = db.scalars(
            select(Notification)
            .where(
                Notification.user_id.in_(admin_ids),
                Notification.type == notification_type,
                Notification.is_read.is_(False),
                Notification.created_at >= cutoff,
            )
            .order_by(Notification.created_at.desc())
        ).all()
        recent_by_admin: dict[UUID, Notification] = {}
        for row in recent_rows:
            recent_by_admin.setdefault(row.user_id, row)

        fresh_admin_ids = []
        for admin_id in admin_ids:
            recent = recent_by_admin.get(admin_id)
            if recent is not None:
                occurrences = (recent.data or {}).get("occurrences", 1) + 1
                recent.title = title
                recent.body = f"{body} ({occurrences} similar alerts since you last checked)"
                recent.data = {**(recent.data or {}), "occurrences": occurrences}
                continue
            fresh_admin_ids.append(admin_id)
            db.add(
                Notification(
                    user_id=admin_id, role=UserRole.ADMIN, type=notification_type,
                    title=title, body=body, data=data, order_id=order_id,
                )
            )

        if fresh_admin_ids:
            if background_tasks is not None:
                background_tasks.add_task(send_push_to_users_in_background, fresh_admin_ids, title, body, data)
            else:
                send_push_to_users(db, fresh_admin_ids, title, body, data=data)
        # Only reached once every write above (and the synchronous
        # dispatch, when not backgrounded) completed without raising —
        # never a count the failure boundary's own rollback invalidated.
        notified_count = len(admin_ids)
    return notified_count


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
    # Notification Preferences (Phase 24) — "promotional notifications
    # should be separately controllable." This is the one call site that
    # actually sends them; every customer who has opted out of
    # `promotions` specifically is excluded here, independent of every
    # other category.
    customer_ids = _filter_users_wanting(db, customer_ids, NotificationType.PROMOTION)
    notified = 0
    with _notification_failure_boundary(db, notification_type=NotificationType.PROMOTION.value):
        data = build_notification_data(NotificationDeepLinkCategory.PROMOTION)
        for user_id in customer_ids:
            db.add(
                Notification(
                    user_id=user_id, role=UserRole.CUSTOMER, type=NotificationType.PROMOTION,
                    title=title, body=body, data=data,
                )
            )
        notified = send_push_to_users(db, customer_ids, title, body, data=data)
    db.commit()
    return notified


def notify_rider_account_approved(db: Session, rider: User) -> None:
    """Notifications & Communication System Phase 7 — moved here from
    rider_service.update_rider_verification, which previously constructed
    the Notification row and dispatched the push directly. "Business
    routes must not contain notification delivery logic" applies to every
    caller, not just the ones already routed through orders.py/payments.py
    — rider_service.py is itself a business-logic service, and account
    approval/suspension are business events like any other.

    Notification Preferences (Phase 24) — deliberately never gated by
    preference (see _NOTIFICATION_CATEGORY's own note on why
    ACCOUNT_APPROVED/ACCOUNT_SUSPENDED are left out of it): this is the
    clearest case of "transactional notifications should remain enabled
    where necessary for service operation" — it gates whether a rider
    can even go online and work at all, not a purely informational
    update a system_notifications toggle should be able to silence."""
    if not _notifications_enabled(db):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.ACCOUNT_APPROVED.value):
        title = "Account approved"
        body = "Your rider account has been approved. You can now go online and accept deliveries."
        data = build_notification_data(NotificationDeepLinkCategory.ACCOUNT_APPROVED)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.ACCOUNT_APPROVED,
                title=title, body=body, data=data,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_rider_account_suspended(db: Session, rider: User) -> None:
    """See notify_rider_account_approved's own note — the same
    consolidation, for the suspension side. Also never preference-gated,
    for the exact same reason."""
    if not _notifications_enabled(db):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.ACCOUNT_SUSPENDED.value):
        title = "Account suspended"
        body = "Your rider account has been suspended. Contact support for details."
        data = build_notification_data(NotificationDeepLinkCategory.ACCOUNT_SUSPENDED)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.ACCOUNT_SUSPENDED,
                title=title, body=body, data=data,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_rider_reassigned_away(db: Session, rider: User, order: Order) -> None:
    """Notifications & Communication System Phase 11 — Rider Notification
    Center, "order changes." admin_reassign_rider (app/services/orders.py)
    already correctly stops this rider's own location updates from
    broadcasting to the order (Live Rider Tracking Phase 31) and records
    the reassignment in its own audit log — but never told the outgoing
    rider anything at all. Without this, a rider reassigned away from a
    delivery they were actively holding would have no idea it happened;
    their own delivery screen would just silently stop reflecting it."""
    if not _notifications_enabled(db) or not _user_wants(db, rider.id, NotificationType.DELIVERY_UPDATED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.DELIVERY_UPDATED.value, order_id=order.id):
        title = "Delivery reassigned"
        body = f"Order {order.order_number} has been reassigned to another rider and is no longer yours to deliver."
        data = build_notification_data(NotificationDeepLinkCategory.DELIVERY_UPDATED, order_id=order.id)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.DELIVERY_UPDATED,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_rider_document_reviewed(db: Session, rider: User, document: RiderDocument) -> None:
    """Phase 11 — the other half of "account/document alerts": a rider
    previously only ever heard about DOCUMENT_SUBMITTED indirectly (it's
    an admin-facing alert, notify_admins) — they were never told the
    *outcome* once an admin actually reviewed it. Called after the
    document's verification_status has already been set to its final
    APPROVED/REJECTED value (admin_riders.py::_transition_document)."""
    # DOCUMENT_APPROVED/DOCUMENT_REJECTED share one category
    # (system_notifications) — checked once here with either, since
    # which branch fires below doesn't change the answer.
    if not _notifications_enabled(db) or not _user_wants(db, rider.id, NotificationType.DOCUMENT_APPROVED):
        return
    document_label = document.document_type.value.replace("_", " ").title()
    with _notification_failure_boundary(db, notification_type=NotificationType.DOCUMENT_APPROVED.value):
        if document.verification_status == DocumentVerificationStatus.APPROVED:
            notification_type = NotificationType.DOCUMENT_APPROVED
            title = "Document approved"
            body = f"Your {document_label} has been approved."
        else:
            notification_type = NotificationType.DOCUMENT_REJECTED
            title = "Document rejected"
            body = f"Your {document_label} was rejected."
            if document.rejection_reason:
                body += f" Reason: {document.rejection_reason}"
        data = build_notification_data(NotificationDeepLinkCategory.DOCUMENT_REVIEWED)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=notification_type,
                title=title, body=body, data=data,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_rider_cod_settlement_due(db: Session, rider: User, outstanding_amount: Decimal) -> None:
    """Phase 11 — "COD-related operational alerts." COD_SETTLEMENT_DUE
    previously only ever alerted admins (notify_admins, from the same
    threshold check in rider_deliveries.py) — the rider whose own balance
    triggered it was never told, even though they're the one who actually
    needs to go remit it. Same NotificationType, a rider-appropriate
    first-person copy — role (Phase 3) is what distinguishes this row
    from the admin's own copy of the same underlying event, not a second
    type."""
    if not _notifications_enabled(db) or not _user_wants(db, rider.id, NotificationType.COD_SETTLEMENT_DUE):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.COD_SETTLEMENT_DUE.value):
        title = "COD settlement due"
        body = f"You have an outstanding COD balance of {outstanding_amount:.2f} awaiting settlement."
        data = build_notification_data(NotificationDeepLinkCategory.COD_SETTLEMENT_DUE)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.COD_SETTLEMENT_DUE,
                title=title, body=body, data=data,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_rider_cod_collection_required(db: Session, rider: User, order: Order) -> None:
    """COD Notifications (Phase 22) — "collection required." Fired once,
    the moment a COD order becomes OUT_FOR_DELIVERY — the point at which
    the rider is actually about to hand it over and needs the reminder,
    not earlier (a rider assigned to an order that's still PREPARING has
    nothing to act on yet). Reuses COD_PENDING (catalogued in Phase 5,
    never wired until now) — "pending" describes the collection's own
    state from the rider's point of view at this moment, the same
    "dormant type wired to its real trigger" pattern PAYMENT_SUCCESS and
    SYSTEM_ALERT both followed before it. Deliberately says only the
    amount this rider already needs to know to do their job — no
    customer payment details, no other order's figures."""
    if not _notifications_enabled(db) or not _user_wants(db, rider.id, NotificationType.COD_PENDING):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.COD_PENDING.value, order_id=order.id):
        title = "Cash collection required"
        body = f"Collect {order.total} in cash for order {order.order_number} on delivery."
        data = build_notification_data(NotificationDeepLinkCategory.COD_COLLECTION_REQUIRED, order_id=order.id)
        db.add(
            Notification(
                user_id=rider.id, role=UserRole.RIDER, type=NotificationType.COD_PENDING,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, rider.id, title, body, data=data)


def notify_customer_cod_collected(db: Session, payment: Payment) -> None:
    """COD Notifications (Phase 22) — "COD collected," the Cash-on-
    Delivery counterpart to notify_customer_payment_success: a customer
    who paid online already gets a "payment successful" confirmation
    the moment it's verified; a customer who pays cash previously got no
    equivalent confirmation at all once the rider actually collected it.
    Reuses COD_COLLECTED (catalogued in Phase 5, never wired until now).
    Deliberately never wired for the restaurant owner's side (Phase 19's
    own reasoning still applies: cash is collected near the end of
    delivery, long after the restaurant already prepared and handed off
    the food — nothing left for them to act on)."""
    if not _notifications_enabled(db) or not _user_wants(db, payment.user_id, NotificationType.COD_COLLECTED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.COD_COLLECTED.value, order_id=payment.order_id):
        title = "Cash payment received"
        body = f"We've received your cash payment of {payment.amount}."
        data = build_notification_data(NotificationDeepLinkCategory.COD_COLLECTED, order_id=payment.order_id)
        db.add(
            Notification(
                user_id=payment.user_id, role=UserRole.CUSTOMER, type=NotificationType.COD_COLLECTED,
                title=title, body=body, data=data, order_id=payment.order_id,
            )
        )
        send_push_to_user(db, payment.user_id, title, body, data=data)


def notify_customer_payment_success(db: Session, payment: Payment) -> None:
    """Notifications & Communication System Phase 8 — Event-Driven
    Notification Hooks. Payment.payment_status transitioning to PAID
    (PaymentService.verify_payment, the actively-wired online-payment
    verification flow — not app/services/payments.py's simpler,
    COD-oriented one) is a real, already-firing business event with no
    prior customer-facing notification at all, despite PAYMENT_SUCCESS
    existing in the catalog since Phase 5 specifically anticipating this.
    Called from the caller's own success branch, before its own commit —
    the same choke-point-adjacent pattern every other notify_* call
    already follows, not a new architectural style."""
    if not _notifications_enabled(db) or not _user_wants(db, payment.user_id, NotificationType.PAYMENT_SUCCESS):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.PAYMENT_SUCCESS.value, order_id=payment.order_id):
        title = "Payment successful"
        body = f"Your payment of {payment.amount} {payment.currency} was received."
        data = build_notification_data(NotificationDeepLinkCategory.PAYMENT_SUCCESS, order_id=payment.order_id)
        db.add(
            Notification(
                user_id=payment.user_id, role=UserRole.CUSTOMER, type=NotificationType.PAYMENT_SUCCESS,
                title=title, body=body, data=data, order_id=payment.order_id,
            )
        )
        send_push_to_user(db, payment.user_id, title, body, data=data)


def notify_customer_refund_initiated(db: Session, refund: Refund, payment: Payment) -> None:
    """Phase 8 — refund_service.create_refund reaching RefundStatus.PROCESSING
    (Razorpay accepted the refund request but the bank/network hasn't
    confirmed it yet) is a genuine, already-firing event with no
    notification today. Not called for a refund that lands directly on
    COMPLETED (COD, or an instantly-"processed" online refund) — that
    case goes straight to notify_customer_refund_completed instead, so a
    customer whose refund was instant is never told "initiated" followed
    immediately by "completed" for the same event."""
    if not _notifications_enabled(db) or not _user_wants(db, payment.user_id, NotificationType.REFUND_INITIATED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.REFUND_INITIATED.value, order_id=refund.order_id):
        title = "Refund initiated"
        body = f"A refund of {refund.amount} {payment.currency} has been initiated for your order and is being processed."
        data = build_notification_data(NotificationDeepLinkCategory.REFUND, order_id=refund.order_id)
        db.add(
            Notification(
                user_id=payment.user_id, role=UserRole.CUSTOMER, type=NotificationType.REFUND_INITIATED,
                title=title, body=body, data=data, order_id=refund.order_id,
            )
        )
        send_push_to_user(db, payment.user_id, title, body, data=data)


def notify_customer_refund_completed(db: Session, refund: Refund, payment: Payment) -> None:
    """Phase 8 — the other half of the refund lifecycle: a refund actually
    settling, whether that happens synchronously inside create_refund
    (COD, or an instant online "processed" result) or asynchronously via
    Razorpay's refund.processed webhook (webhook_service.py) resolving an
    earlier PROCESSING refund. Called from both places — a customer whose
    refund settles instantly gets exactly one notification (this one,
    never REFUND_INITIATED first); a customer whose refund settles later
    gets both, in order."""
    if not _notifications_enabled(db) or not _user_wants(db, payment.user_id, NotificationType.REFUND_COMPLETED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.REFUND_COMPLETED.value, order_id=refund.order_id):
        title = "Refund completed"
        body = f"Your refund of {refund.amount} {payment.currency} has been completed."
        data = build_notification_data(NotificationDeepLinkCategory.REFUND, order_id=refund.order_id)
        db.add(
            Notification(
                user_id=payment.user_id, role=UserRole.CUSTOMER, type=NotificationType.REFUND_COMPLETED,
                title=title, body=body, data=data, order_id=refund.order_id,
            )
        )
        send_push_to_user(db, payment.user_id, title, body, data=data)


def _resolve_restaurant_owner(db: Session, order: Order) -> User | None:
    """Notifications & Communication System Phase 12 — Restaurant Owner
    Notifications. order.restaurant_id is a denormalized str snapshot,
    not a strict FK (see Order's own model comments) — the same
    try/except-ValueError resolution pattern build_tracking_snapshot
    (Live Rider Tracking) already established for this exact field.
    Returns None (never raises) for a historical order whose restaurant
    was since deleted, or a malformed id — a missing recipient is a
    silent no-op here, the same as every other notify_* function's
    behavior when there's nobody to tell."""
    if not order.restaurant_id:
        return None
    try:
        restaurant = db.get(Restaurant, UUID(order.restaurant_id))
    except ValueError:
        return None
    return db.get(User, restaurant.owner_id) if restaurant else None


def notify_restaurant_new_order(db: Session, order: Order) -> None:
    """Phase 12 — "new order." The actionable moment a restaurant owner
    needs to review and accept/reject — fired from the same place
    notify_order_placed already tells the customer, not from
    accept_restaurant_order (there is no separate "order accepted"
    notification: that's the owner's own synchronous action, with its
    own immediate UI feedback, the same reasoning already applied to a
    rider's own accept_delivery in Phase 11)."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.RESTAURANT_NEW_ORDER):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.RESTAURANT_NEW_ORDER.value, order_id=order.id):
        title = "New order"
        body = f"New order {order.order_number} received — {order.item_count} item(s), {order.total}."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_NEW_ORDER, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.RESTAURANT_NEW_ORDER,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_order_cancelled(db: Session, order: Order) -> None:
    """Phase 12 — "order cancelled." A customer (or admin) cancelling an
    order the restaurant may already be preparing — genuinely actionable
    for them, distinct from the customer's own ORDER_CANCELLED."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.RESTAURANT_ORDER_CANCELLED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.RESTAURANT_ORDER_CANCELLED.value, order_id=order.id):
        title = "Order cancelled"
        body = f"Order {order.order_number} has been cancelled."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_ORDER_CANCELLED, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.RESTAURANT_ORDER_CANCELLED,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_rider_assigned(db: Session, order: Order) -> None:
    """Phase 12 — "rider assigned." Lets the restaurant time food
    preparation against when a rider will actually arrive for pickup.
    Reuses RIDER_ASSIGNED (already exists, customer-facing) rather than a
    new type — role (Phase 3) is what distinguishes this row from the
    customer's own copy of the same underlying event, the same pattern
    already used for COD_SETTLEMENT_DUE in Phase 11."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.RIDER_ASSIGNED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.RIDER_ASSIGNED.value, order_id=order.id):
        title = "Rider assigned"
        body = f"A delivery partner has been assigned to pick up order {order.order_number}."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_RIDER_ASSIGNED, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.RIDER_ASSIGNED,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_payment_issue(db: Session, order: Order) -> None:
    """Phase 12 — "operational alerts" / the payment half of "payment/
    settlement events." Reuses PAYMENT_UPDATE (already used for the
    customer's own payment-failure notification) — a restaurant-facing
    heads-up that an order's online payment failed verification, since
    that affects whether they should actually fulfil it.

    "Settlement events" — the other half this phase's checklist names —
    has no underlying feature to connect to: this codebase has no
    restaurant payout/settlement system at all (confirmed by a
    whole-codebase search; only a *rider* COD settlement concept
    exists, already covered in Phase 11). Documented here as a real,
    deliberate scope boundary, not an oversight — inventing a trigger
    for a feature that doesn't exist would mean either a fake event or
    building a whole new payout system, well beyond this phase's own
    "integrate with existing business events" framing."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.PAYMENT_UPDATE):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.PAYMENT_UPDATE.value, order_id=order.id):
        title = "Payment issue"
        body = f"Payment verification failed for order {order.order_number}."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_PAYMENT_ISSUE, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.PAYMENT_UPDATE,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_payment_confirmed(db: Session, order: Order) -> None:
    """Phase 19 — "payment confirmation where relevant." Only wired into
    the online (razorpay) payment success path (see
    PaymentService.verify_payment), never COD: restaurant_dashboard.py's
    own pending-order queue already hides a razorpay order from the
    restaurant entirely until Order.is_paid is true (payment_confirmed
    filter), so for those orders this is the actual moment an order
    becomes visible/actionable to them — genuinely relevant. A COD
    order's "payment" isn't collected until the rider hands over cash
    near the end of the delivery, by which point the restaurant has
    already prepared and handed off the food; a payment-confirmed alert
    at that stage would tell them nothing they could still act on, so
    "where relevant" deliberately excludes it rather than firing a
    notification with no real use."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.PAYMENT_UPDATE):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.PAYMENT_UPDATE.value, order_id=order.id):
        title = "Payment confirmed"
        body = f"Payment for order {order.order_number} has been confirmed."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_PAYMENT_CONFIRMED, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.PAYMENT_UPDATE,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_delivery_exception(db: Session, order: Order) -> None:
    """Phase 19 — "delivery exception." Fired from admin_reassign_rider
    (orders.py) — the one real delivery-exception path this codebase
    actually has today (see notify_rider_reassigned_away's own note):
    something went wrong with the rider originally assigned to this
    restaurant's order badly enough that an admin had to step in and
    swap them out. Previously only the outgoing rider was told anything
    at all; the restaurant — who may be timing food prep/handoff against
    a rider who's no longer coming — had no way to know. Reuses
    DELIVERY_UPDATED (already the rider's own type for this same
    underlying event) rather than a new type — role is what
    distinguishes this row, the same convention this whole package
    already follows."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.DELIVERY_UPDATED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.DELIVERY_UPDATED.value, order_id=order.id):
        title = "Delivery partner changed"
        body = f"The delivery partner for order {order.order_number} has changed."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_DELIVERY_EXCEPTION, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.DELIVERY_UPDATED,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


def notify_restaurant_delivery_completed(db: Session, order: Order) -> None:
    """Live Delivery Notifications (Phase 23) — "delivery completed," the
    restaurant's own side of ORDER_DELIVERED (already the customer's own
    type for this same underlying event — role is what distinguishes
    this row, the same convention every other restaurant hook already
    follows). Closes the loop for the restaurant: for a COD order in
    particular, this is their confirmation that the delivery — and the
    cash handoff — actually completed, not just that a rider left their
    kitchen."""
    if not _notifications_enabled(db):
        return
    owner = _resolve_restaurant_owner(db, order)
    if owner is None or not _user_wants(db, owner.id, NotificationType.ORDER_DELIVERED):
        return
    with _notification_failure_boundary(db, notification_type=NotificationType.ORDER_DELIVERED.value, order_id=order.id):
        title = "Order delivered"
        body = f"Order {order.order_number} has been delivered."
        data = build_notification_data(NotificationDeepLinkCategory.RESTAURANT_DELIVERY_COMPLETED, order_id=order.id)
        db.add(
            Notification(
                user_id=owner.id, role=UserRole.RESTAURANT_OWNER, type=NotificationType.ORDER_DELIVERED,
                title=title, body=body, data=data, order_id=order.id,
            )
        )
        send_push_to_user(db, owner.id, title, body, data=data)


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


def count_unread_notifications(db: Session, user_id: UUID) -> int:
    """Notifications & Communication System Phase 9 — In-App Notification
    API. A dedicated count query, not len(list_notifications(...)) — the
    list is capped at _MAX_NOTIFICATIONS_RETURNED and sorted by recency,
    neither of which this needs; a plain COUNT(*) WHERE is_read = false is
    both cheaper and correct even for an account with more than 100
    notifications (a capped list would undercount unread ones past the
    cap)."""
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .count()
    )


def mark_notification_read(db: Session, user_id: UUID, notification_id: UUID) -> Notification:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        # Observability (Phase 43) — only on the genuine first transition,
        # never for a duplicate/retried mark-read of an already-read
        # notification (Phase 26's own idempotency) — a false repeat
        # "opened" event would misrepresent how many times this
        # notification was actually acted on.
        log_event(logger, "notification_opened", notification_id=notification.id, notification_type=notification.type.value)
    db.commit()
    db.refresh(notification)
    return notification


def mark_all_notifications_read(db: Session, user_id: UUID) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": datetime.now(UTC)})
    )
    db.commit()
    if updated:
        log_event(logger, "notification_marked_read", count=updated)
    return updated


# Notification History/Retention (Phase 34) — documented, adjustable
# business rules, the same pattern as COD_SETTLEMENT_DUE_THRESHOLD/
# _PAYMENT_EXPIRY_WINDOW/_ADMIN_ALERT_AGGREGATION_WINDOW elsewhere in
# this file.
#
# READ notifications: the user has already seen and acted on them —
# in-app history beyond 90 days has steeply diminishing value, and this
# is the real fix for "avoid storing unlimited notification history"
# (list_notifications' own 100-row cap only bounds what one query
# returns; the table itself still grew forever without this).
_NOTIFICATION_RETENTION_DAYS_READ = 90
# UNREAD notifications are deliberately NOT purged on the same short
# schedule — "do not delete active/important operational notifications
# prematurely": a notification nobody has acknowledged yet is still
# "active" from that user's own point of view, however old. A much
# longer backstop (not "never") still applies, purely to bound
# worst-case table growth from a notification that will truly never be
# read (e.g. a long-abandoned account) — an order of magnitude longer
# than the read-retention window, never a routine cleanup trigger.
_NOTIFICATION_RETENTION_DAYS_UNREAD = 365


def purge_old_notifications(db: Session) -> int:
    """Cleanup strategy (Phase 34) — this codebase has no
    scheduler/background-job system (confirmed repeatedly elsewhere,
    e.g. PaymentService's own lazy order-expiry check), so this is a
    plain, idempotent, callable function — safe to invoke from an admin
    action now, and exactly what a future scheduled job (see Phase 42's
    own decision on background processing) would call, rather than
    speculatively building a scheduler ahead of that decision. Bounded
    by the (is_read, created_at) index added alongside this function, so
    this scales to however large the table has grown, not just however
    large it is today."""
    now = datetime.now(UTC)
    read_cutoff = now - timedelta(days=_NOTIFICATION_RETENTION_DAYS_READ)
    unread_cutoff = now - timedelta(days=_NOTIFICATION_RETENTION_DAYS_UNREAD)
    deleted = (
        db.query(Notification)
        .filter(
            or_(
                and_(Notification.is_read.is_(True), Notification.created_at < read_cutoff),
                and_(Notification.is_read.is_(False), Notification.created_at < unread_cutoff),
            )
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
