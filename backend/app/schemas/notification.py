import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationType


class NotificationDeepLinkCategory(str, enum.Enum):
    """Notifications & Communication System Phase 6 — Notification Payload
    Standard. The value every notify_* call site puts in its `data["type"]`
    field — deliberately a *coarser* concept than NotificationType itself:
    several distinct NotificationType values (ORDER_PLACED, CONFIRMED,
    PREPARING, ..., CANCELLED) all route the customer to the exact same
    screen (`/track/[id]`), so the client's own deep-link handler groups
    on this category, not on the precise type. Centralizing these string
    values here (they previously existed as scattered literals across
    notifications.py/rider_service.py, one call site at a time) is this
    phase's actual job — the values themselves are unchanged from what's
    already live and already matched by customer-mobile's own
    handleDeepLink, so nothing about existing behavior changes, only
    where the string is defined."""

    ORDER_STATUS = "order_status"
    DELIVERY_CANCELLED = "delivery_cancelled"
    RIDER_APPROACHING = "rider_approaching"
    PAYMENT_FAILED = "payment_failed"
    NEW_DELIVERY = "new_delivery"
    ACCOUNT_APPROVED = "account_approved"
    ACCOUNT_SUSPENDED = "account_suspended"
    PROMOTION = "promotion"
    # Notifications & Communication System Phase 8 — Event-Driven
    # Notification Hooks. New categories for the
    # genuinely-firing payment-success/refund events this phase connects;
    # not yet matched by any client-side deep-link handler (a later phase,
    # same as several categories above once were before their own
    # client-side handling landed).
    PAYMENT_SUCCESS = "payment_success"
    REFUND = "refund"
    # Notifications & Communication System Phase 11 — Rider Notification
    # Center. DELIVERY_UPDATED covers "order changes" that aren't a
    # straightforward status transition or an outright cancellation —
    # currently: a rider being reassigned away from a delivery they were
    # holding. DOCUMENT_REVIEWED covers both approval and rejection
    # outcomes for one submitted document — the two share a category
    # since both route to the same place (the rider's own document list).
    DELIVERY_UPDATED = "delivery_updated"
    DOCUMENT_REVIEWED = "document_reviewed"
    COD_SETTLEMENT_DUE = "cod_settlement_due"
    # Notifications & Communication System Phase 22 — COD Notifications.
    COD_COLLECTION_REQUIRED = "cod_collection_required"
    COD_COLLECTED = "cod_collected"
    # Notifications & Communication System Phase 12 — Restaurant Owner
    # Notifications. business-web's own deep-link categories — this app
    # has its own routes, distinct from customer-mobile's, so these are
    # new categories rather than reusing ORDER_STATUS/PAYMENT_FAILED.
    RESTAURANT_NEW_ORDER = "restaurant_new_order"
    RESTAURANT_ORDER_CANCELLED = "restaurant_order_cancelled"
    RESTAURANT_RIDER_ASSIGNED = "restaurant_rider_assigned"
    RESTAURANT_PAYMENT_ISSUE = "restaurant_payment_issue"
    # Notifications & Communication System Phase 19 — Restaurant Order
    # Notifications.
    RESTAURANT_PAYMENT_CONFIRMED = "restaurant_payment_confirmed"
    RESTAURANT_DELIVERY_EXCEPTION = "restaurant_delivery_exception"
    # Notifications & Communication System Phase 23 — Live Delivery
    # Notifications.
    RESTAURANT_DELIVERY_COMPLETED = "restaurant_delivery_completed"


def build_notification_data(
    category: NotificationDeepLinkCategory, *, order_id: UUID | None = None, status: str | None = None
) -> dict[str, str]:
    """The one standard shape for a notification's `data` payload — sent
    to the push provider and persisted on the Notification row alike.
    Deliberately narrow (category/order_id/status as named parameters,
    not **kwargs or an open dict) rather than a comment asking nicely:
    "keep payloads small" and "never include unnecessary personal
    information" are enforced structurally here — a caller cannot stuff
    an email address, a raw amount, or any other field into this payload
    without first changing this function's own signature, which is
    exactly the speed bump a payload-security rule like this needs to
    actually hold under future changes, not just today."""
    data: dict[str, str] = {"type": category.value}
    if order_id is not None:
        data["order_id"] = str(order_id)
    if status is not None:
        data["status"] = status
    return data


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: NotificationType
    title: str
    body: str
    order_id: UUID | None
    # Notifications & Communication System Phase 3 — the same deep-link context a live push already carries in
    # its own `data` field, now also available when re-fetching history
    # (a client that missed the live push still gets the full context on
    # its next GET /notifications, not just order_id). role/channel/
    # status/sent_at/failed_at are deliberately not exposed here yet —
    # operational fields with no client-facing use until a later phase
    # gives them one.
    data: dict[str, Any] | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None


class MarkAllReadResponse(BaseModel):
    updated: int


class NotificationCleanupResult(BaseModel):
    deleted: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class PromotionalBroadcastCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=1000)


class PromotionalBroadcastResult(BaseModel):
    notified_customers: int


class NotificationPreferenceRead(BaseModel):
    """Notification Preferences (Phase 24) — per-user, per-category
    toggles. Every category defaults to True (see NotificationPreference's
    own model docstring for why) — this response always reflects a real,
    already-materialized row (get_or_create_notification_preference),
    never a client-side guess at what the defaults are."""

    model_config = ConfigDict(from_attributes=True)

    order_updates: bool
    delivery_updates: bool
    payment_updates: bool
    promotions: bool
    system_notifications: bool


class NotificationPreferenceUpdate(BaseModel):
    """All fields optional — PATCH semantics: only the categories a
    client actually sends are changed, every other one keeps whatever
    it was already set to.

    Notification Preference API (Phase 25) — "validate allowed
    preference keys." extra="forbid" is this codebase's first use of
    that config (no other schema needs it — most PATCH bodies here are
    forgiving by convention), deliberately added here: a client typo'ing
    a category name (e.g. "oder_updates") must get a clean 422 telling
    them so, not have it silently ignored while they believe the change
    took effect."""

    model_config = ConfigDict(extra="forbid")

    order_updates: bool | None = None
    delivery_updates: bool | None = None
    payment_updates: bool | None = None
    promotions: bool | None = None
    system_notifications: bool | None = None
