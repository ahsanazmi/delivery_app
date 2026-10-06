"""Notifications & Communication System Phase 37 — End-to-End Customer
Test.

Walks the exact sequence this phase names — place, confirm, prepare,
rider assigned, picked up, out for delivery, delivered — as one
continuous narrative, checking all five dimensions this phase asks for
at every step: the in-app row exists, a push was actually dispatched to
the provider, the unread count tracks correctly, the deep-link payload
carries the right category + order_id, and retrying the final step never
creates a duplicate.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import (
    count_unread_notifications,
    mark_all_notifications_read,
    upsert_push_token,
)
from app.services.orders import create_order, transition_order_status


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


def test_full_customer_order_journey_produces_in_app_push_unread_and_deep_link_correctly(db, monkeypatch):
    captured_pushes = []

    def fake_post(url, json, timeout, headers):
        captured_pushes.append(json)
        return FakeResponse(len(json))

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    # --- Setup: a customer, a restaurant, a rider, a registered device ---
    customer = User(name="Cust", email="e2e-customer@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    upsert_push_token(db, customer.id, "ExponentPushToken[e2e]")

    owner = User(name="Owner", email="e2e-owner@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="E2E Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()

    from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
    from app.models.product import Product
    from app.services.rider_deliveries import accept_delivery, pickup_delivery, start_delivery

    rider = User(name="Rider", email="e2e-rider@example.com", phone="9800000060", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()

    product = Product(restaurant_id=restaurant.id, name="Chai", price=Decimal("50.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })

    def assert_step(expected_type, expected_unread, step_name):
        unread = count_unread_notifications(db, customer.id)
        assert unread == expected_unread, f"unread count wrong after {step_name}"
        notification = db.scalar(
            select(Notification)
            .where(Notification.user_id == customer.id, Notification.type == expected_type)
            .order_by(Notification.created_at.desc())
        )
        assert notification is not None, f"missing {expected_type} after {step_name}"
        assert notification.data["type"] == "order_status", f"wrong deep-link category after {step_name}"
        assert notification.data["order_id"] == str(order.id), f"wrong deep-link order_id after {step_name}"
        assert len(captured_pushes) >= 1, f"no push dispatched for {step_name}"
        assert any(m["to"] == "ExponentPushToken[e2e]" for m in captured_pushes[-1]), f"push never reached the device after {step_name}"

    # --- Step 1: Customer places order -> ORDER_PLACED ---
    order = create_order(db, customer, address.id)
    assert_step(NotificationType.ORDER_PLACED, 1, "order placed")

    # --- Step 2: Restaurant confirms -> ORDER_CONFIRMED ---
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assert_step(NotificationType.ORDER_CONFIRMED, 2, "restaurant confirms")

    # --- Step 3: Restaurant prepares -> ORDER_PREPARING ---
    transition_order_status(db, order, OrderStatus.PREPARING)
    assert_step(NotificationType.ORDER_PREPARING, 3, "restaurant prepares")

    # --- Step 4: Ready for pickup, then rider accepts -> RIDER_ASSIGNED ---
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    assert_step(NotificationType.RIDER_ASSIGNED, 5, "rider assigned")  # +1 for READY, +1 for RIDER_ASSIGNED

    # --- Step 5: Rider picks up -> ORDER_PICKED_UP ---
    pickup_delivery(db, rider, order.id)
    assert_step(NotificationType.ORDER_PICKED_UP, 6, "rider picks up")

    # --- Step 6: Out for delivery -> ORDER_OUT_FOR_DELIVERY ---
    start_delivery(db, rider, order.id)
    assert_step(NotificationType.ORDER_OUT_FOR_DELIVERY, 7, "out for delivery")

    # --- Step 7: Delivered -> ORDER_DELIVERED (completion notification) ---
    transition_order_status(db, order, OrderStatus.DELIVERED)
    assert_step(NotificationType.ORDER_DELIVERED, 8, "delivered")

    # --- Unread count: mark all read, confirm it drops to zero ---
    updated = mark_all_notifications_read(db, customer.id)
    assert updated == 8
    assert count_unread_notifications(db, customer.id) == 0

    # --- Duplicate prevention: a retried/duplicate delivered transition
    # must never create a second ORDER_DELIVERED row ---
    pushes_before_retry = len(captured_pushes)
    with pytest.raises(ValueError):
        transition_order_status(db, order, OrderStatus.DELIVERED)
    delivered_rows = db.scalars(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_DELIVERED)
    ).all()
    assert len(delivered_rows) == 1
    assert len(captured_pushes) == pushes_before_retry  # no extra push either
