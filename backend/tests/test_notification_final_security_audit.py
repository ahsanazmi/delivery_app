"""Notifications & Communication System Phase 45 — Final Notification
Security Audit.

Authentication, authorization, IDOR protection, device-token ownership,
notification ownership, and role isolation were already proven
exhaustively in Phase 35's own dedicated audit (test_notification_
security_audit.py) and Phase 39's tenant-isolation E2E — not re-derived
here. Preference security (extra="forbid", cross-user) was proven in
Phase 25. Duplicate prevention in Phase 30. Rate limiting/anti-spam in
Phase 33. This file covers the two angles those files don't: payload
security (a live sweep of real Notification.data payloads across
several different roles/events, not just the one narrow builder
function in isolation) and provider secret protection (EXPO_ACCESS_TOKEN
never leaking into a stored row or an API response).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.notification import NotificationDeepLinkCategory, build_notification_data
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import notify_admins, notify_rider_cod_collection_required
from app.services.orders import create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, pickup_delivery, start_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


_FORBIDDEN_PAYLOAD_SUBSTRINGS = (
    "Bearer ", "eyJ", "password", "razorpay_key_secret", "card_number", "cvv", "upi_id",
)


def _assert_payload_is_clean(value) -> None:
    text = str(value)
    for forbidden in _FORBIDDEN_PAYLOAD_SUBSTRINGS:
        assert forbidden.lower() not in text.lower(), f"forbidden content found in notification payload: {text!r}"


# ---------------------------------------------------------------------------
# Payload security
# ---------------------------------------------------------------------------


def test_build_notification_data_cannot_structurally_carry_more_than_type_order_id_status():
    full = build_notification_data(NotificationDeepLinkCategory.ORDER_STATUS, order_id=None, status="confirmed")
    # order_id=None is omitted entirely — confirms the function's own
    # "never include a field with nothing in it" behavior, not just "the
    # allowed field list is short."
    assert set(full.keys()) <= {"type", "status"}

    minimal = build_notification_data(NotificationDeepLinkCategory.PROMOTION)
    assert set(minimal.keys()) == {"type"}


def test_live_sweep_of_real_notification_payloads_across_several_roles_never_leaks_anything(db):
    customer = User(name="Cust", email="audit-cust@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    owner = User(name="Owner", email="audit-owner@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Audit Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    rider = User(name="Rider", email="audit-rider@example.com", phone="9800000099", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    admin = User(name="Admin", email="audit-admin@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
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

    # Customer-facing, restaurant-facing, and rider-facing events, plus
    # an admin operational alert — a representative spread across every
    # role this system notifies.
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    pickup_delivery(db, rider, order.id)
    start_delivery(db, rider, order.id)
    notify_rider_cod_collection_required(db, rider, order)
    notify_admins(db, NotificationType.ORDER_ISSUE, "Order issue", f"Order {order.order_number} needs review.", order_id=order.id)
    db.commit()

    all_notifications = db.scalars(select(Notification)).all()
    assert len(all_notifications) > 0
    for notification in all_notifications:
        _assert_payload_is_clean(notification.title)
        _assert_payload_is_clean(notification.body)
        _assert_payload_is_clean(notification.data)
        # Payload size discipline (Phase 6) — never more than the
        # narrow set of keys build_notification_data can ever produce.
        if notification.data:
            assert set(notification.data.keys()) <= {"type", "order_id", "status", "occurrences"}


# ---------------------------------------------------------------------------
# Provider secret protection
# ---------------------------------------------------------------------------


def test_expo_access_token_never_leaks_into_a_stored_notification_or_an_api_response(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.EXPO_ACCESS_TOKEN", "super-secret-expo-token-xyz")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"status": "ok"}]}

    captured_headers = {}

    def fake_post(url, json, timeout, headers):
        captured_headers.update(headers)
        return FakeResponse()

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    from app.services.notifications import notify_rider_account_approved, upsert_push_token

    rider = User(name="Rider", email="audit-secret@example.com", phone="9800000098", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    upsert_push_token(db, rider.id, "ExponentPushToken[secrettest]")

    notify_rider_account_approved(db, rider)

    # The secret genuinely was used (proves this test exercised the real
    # path, not a no-op) ...
    assert captured_headers.get("Authorization") == "Bearer super-secret-expo-token-xyz"
    # ... but never ends up anywhere a client could ever read it back.
    notification = db.scalar(select(Notification).where(Notification.user_id == rider.id))
    assert notification is not None
    assert "super-secret-expo-token-xyz" not in notification.title
    assert "super-secret-expo-token-xyz" not in notification.body
    assert "super-secret-expo-token-xyz" not in str(notification.data)


def test_expo_access_token_is_never_returned_by_any_notification_api_response():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="audit-api-secret@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
            seed.add(customer)
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            for path in ("/api/v1/customer/notifications", "/api/v1/notifications/preferences"):
                response = client.get(path, headers={"Authorization": f"Bearer {token}"})
                assert "EXPO_ACCESS_TOKEN" not in response.text
                assert "razorpay" not in response.text.lower()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
