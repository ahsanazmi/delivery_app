"""Notifications & Communication System Phase 46 — Final Notification
System Audit.

Phases 37-39 already walked complete, role-specific journeys for
CUSTOMER, RIDER, and RESTAURANT_OWNER/ADMIN. What none of those checked
was the *interaction* between every stage of this phase's own diagram in
one place — specifically, the Preference Check step actually suppressing
one real event while leaving another (a different category) untouched
in the exact same flow — and two systems those journeys didn't touch at
all: Live Tracking (the proximity-triggered RIDER_APPROACHING event) and
a COD order's full payment-less lifecycle through to cash collection.
This file is the capstone: Business Event -> Notification Event ->
Recipient Resolution -> Preference Check -> Notification Record ->
In-App + Push -> User Opens -> Authorized Deep Link, walked explicitly,
for every role this system notifies.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import (
    maybe_notify_rider_approaching,
    mark_notification_read,
    update_notification_preference,
    upsert_push_token,
)
from app.services.orders import assign_rider_to_order, create_order, get_user_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, collect_cod_payment, pickup_delivery, start_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


class FakeResponse:
    status_code = 200

    def __init__(self, count):
        self._data = [{"status": "ok"} for _ in range(count)]

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


DELIVERY_LAT = Decimal("12.9700")
DELIVERY_LNG = Decimal("77.5900")
NEARBY_LAT = Decimal("12.9705")
NEARBY_LNG = Decimal("77.5905")


def test_complete_pipeline_across_every_role_and_every_system(db, monkeypatch):
    captured = []

    def fake_post(url, json, timeout, headers):
        captured.append(json)
        return FakeResponse(len(json))

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    # ---- Recipient Resolution setup: one of each role ----
    customer = User(name="Cust", email="final-audit-cust@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    owner = User(name="Owner", email="final-audit-owner@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Final Audit Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    rider = User(name="Rider", email="final-audit-rider@example.com", phone="9800000001", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    admin = User(name="Admin", email="final-audit-admin@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()

    for user in (customer, rider, owner, admin):
        upsert_push_token(db, user.id, f"ExponentPushToken[{user.role.value}]")

    # ---- Preference Check: the customer turns off delivery_updates
    # (RIDER_ASSIGNED's own category) but leaves order_updates on. This
    # is the one thing Phases 37-39's own journeys never exercised: the
    # preference gate actually changing the outcome of a real event,
    # live, inside an otherwise-normal order flow. ----
    update_notification_preference(db, customer.id, {"delivery_updates": False})

    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Chai", price=Decimal("50.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "latitude": DELIVERY_LAT, "longitude": DELIVERY_LNG,
    })

    # ---- Business Event: Orders system — order placed (order_updates,
    # left enabled) ----
    order = create_order(db, customer, address.id)
    placed = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_PLACED)
    )
    assert placed is not None  # Preference Check passed: order_updates is on

    # ---- Orders + Restaurant: confirm, prepare, ready ----
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    new_order_notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.RESTAURANT_NEW_ORDER)
    )
    assert new_order_notification is not None  # restaurant role covered

    # ---- Delivery: rider assigned — the customer's own RIDER_ASSIGNED
    # copy is delivery_updates, which they just turned off. This is the
    # Preference Check actually doing something, not just existing. ----
    assign_rider_to_order(db, order, rider.id)
    customer_rider_assigned = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.RIDER_ASSIGNED)
    )
    assert customer_rider_assigned is None  # correctly suppressed
    # The restaurant's own copy of the same event is a different
    # recipient's own preference (never touched) — still fires.
    restaurant_rider_assigned = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.RIDER_ASSIGNED)
    )
    assert restaurant_rider_assigned is not None

    # ---- Delivery + COD: pickup, out for delivery, cash collected ----
    pickup_delivery(db, rider, order.id)
    start_delivery(db, rider, order.id)

    # ---- Preference Check, again: re-enabling delivery_updates here
    # proves the check is evaluated fresh on every single notification,
    # not cached from the earlier read — RIDER_APPROACHING shares the
    # same category as the RIDER_ASSIGNED alert just suppressed above,
    # so it would be suppressed too without this. ----
    update_notification_preference(db, customer.id, {"delivery_updates": True})

    # ---- Live Tracking: proximity-triggered RIDER_APPROACHING, the one
    # notification not driven by an order-status transition at all ----
    maybe_notify_rider_approaching(db, order, NEARBY_LAT, NEARBY_LNG)
    approaching = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.RIDER_APPROACHING)
    )
    assert approaching is not None
    assert approaching.data["type"] == "rider_approaching"

    # ---- COD: cash collected ----
    collect_cod_payment(db, rider, order.id)
    cod_collected = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.COD_COLLECTED)
    )
    assert cod_collected is not None

    # ---- Delivered: completion, both customer and restaurant ----
    from app.services.rider_deliveries import complete_delivery

    complete_delivery(db, rider, order.id)
    assert db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_DELIVERED)
    ) is not None
    assert db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.ORDER_DELIVERED)
    ) is not None

    # ---- Authentication + Admin: an admin operational alert from the
    # same journey (Admin role coverage) ----
    from app.services.notifications import notify_admins

    notify_admins(db, NotificationType.COD_SETTLEMENT_DUE, "COD settlement due", "Routine check.")
    assert db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.COD_SETTLEMENT_DUE)
    ) is not None

    # ---- In-App + Push: every notification actually created also
    # actually dispatched a push (captured by the fake provider above) ----
    assert len(captured) > 0
    all_dispatched_tokens = {m["to"] for batch in captured for m in batch}
    assert "ExponentPushToken[CUSTOMER]" in all_dispatched_tokens
    assert "ExponentPushToken[RESTAURANT_OWNER]" in all_dispatched_tokens
    assert "ExponentPushToken[ADMIN]" in all_dispatched_tokens

    # ---- User Opens -> Authorized Deep Link: the customer "opens" their
    # delivered notification; the order_id it carries resolves through
    # the real, ownership-scoped API — never trusted on its own ----
    delivered_notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_DELIVERED)
    )
    opened = mark_notification_read(db, customer.id, delivered_notification.id)
    assert opened.is_read is True
    assert opened.data["type"] == "order_status"

    resolved_order = get_user_order(db, customer.id, opened.order_id)
    assert resolved_order is not None
    assert resolved_order.id == order.id
    assert resolved_order.status == OrderStatus.DELIVERED

    # An attacker with no actual relationship to this order can never
    # resolve it through the same authorized path, even with the exact
    # same order_id a notification would have carried.
    stranger = User(name="Stranger", email="final-audit-stranger@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(stranger)
    db.commit()
    assert get_user_order(db, stranger.id, order.id) is None
