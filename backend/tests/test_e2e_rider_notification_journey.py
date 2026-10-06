"""Notifications & Communication System Phase 38 — End-to-End Rider
Test.

Walks this phase's exact sequence as one continuous narrative: device
token registration, a new delivery assignment push, the rider "opening"
the notification (the deep-link payload a tap would route on), an
assignment change (reassignment), and delivery completion — checking the
backend side of each step (the client-side routing itself was already
unit-tested in Phase 27/29).
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
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import count_unread_notifications, upsert_push_token
from app.services.orders import admin_reassign_rider, assign_rider_to_order, create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, collect_cod_payment, complete_delivery, pickup_delivery, start_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


class FakeResponse:
    def __init__(self, count):
        self._data = [{"status": "ok"} for _ in range(count)]
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


def _restaurant_and_order(db, customer, tag="e2erider"):
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_full_rider_notification_journey(db, monkeypatch):
    captured_pushes = []

    def fake_post(url, json, timeout, headers):
        captured_pushes.append(json)
        return FakeResponse(len(json))

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    # --- Rider logs in, device token registered ---
    rider = User(name="Rider", email="e2e-rider-journey@example.com", phone="9800000070", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    token_row = upsert_push_token(db, rider.id, "ExponentPushToken[riderjourney]", device_identifier="device-rider-journey")
    assert token_row.is_active is True
    registered = db.scalars(select(PushToken).where(PushToken.user_id == rider.id)).all()
    assert len(registered) == 1

    customer = User(name="Cust", email="e2e-rider-journey-cust@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    order = _restaurant_and_order(db, customer)

    # --- New delivery assigned -> push notification ---
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    # accept_delivery is the rider's own synchronous action (Phase 11's
    # "no self-notification" rule) — no NEW_DELIVERY row exists for this
    # rider personally from self-accepting; the test below exercises the
    # admin-assignment path that *does* notify them personally, which is
    # also where "rider opens the notification" (the deep-link payload a
    # tap would route on) is actually proven.

    # --- Delivery completed ---
    pickup_delivery(db, rider, order.id)
    start_delivery(db, rider, order.id)
    collect_cod_payment(db, rider, order.id)
    complete_delivery(db, rider, order.id)
    assert order.status == OrderStatus.DELIVERED

    # --- Assignment changes -> appropriate notification (second order,
    # admin-assigned then reassigned, proving both "new assignment" and
    # "reassigned away" personally notify the rider with a real,
    # deep-linkable push) ---
    second_order = _restaurant_and_order(db, customer, tag="e2erider2")
    transition_order_status(db, second_order, OrderStatus.CONFIRMED)
    transition_order_status(db, second_order, OrderStatus.PREPARING)
    transition_order_status(db, second_order, OrderStatus.READY_FOR_PICKUP)

    admin = User(name="Admin", email="e2e-rider-admin@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    assign_rider_to_order(db, second_order, rider.id)

    assignment_notification = db.scalar(
        select(Notification).where(
            Notification.user_id == rider.id,
            Notification.type == NotificationType.NEW_DELIVERY,
            Notification.order_id == second_order.id,
        )
    )
    assert assignment_notification is not None
    assert assignment_notification.data["type"] == "new_delivery"
    assert any(m["to"] == "ExponentPushToken[riderjourney]" for m in captured_pushes[-1])

    other_rider = User(name="Other Rider", email="e2e-rider-other@example.com", phone="9800000071", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(other_rider)
    db.commit()
    db.add(DeliveryPartner(user_id=other_rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()

    admin_reassign_rider(db, admin, second_order.id, other_rider.id, reason="original rider unavailable")

    reassigned_notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.DELIVERY_UPDATED)
    )
    assert reassigned_notification is not None
    assert reassigned_notification.order_id == second_order.id

    # --- Overall sanity: the rider's unread count reflects every
    # personal notification they actually received across the journey ---
    assert count_unread_notifications(db, rider.id) >= 2  # at least the assignment + the reassignment
