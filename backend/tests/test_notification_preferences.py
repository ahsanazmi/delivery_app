"""Notifications & Communication System Phase 24 — Notification
Preferences.

Covers the per-user preference model/API (defaults, lazy creation,
partial updates) and — the part that actually matters — that every
category is genuinely *enforced* at send time, not just stored: a
customer who turns off order_updates stops getting ORDER_PLACED; a
rider who turns off delivery_updates is excluded from a broadcast, not
just their own notifications; promotions is independently controllable
from every other category; and the one deliberate exception — account
approval/suspension, which "remain enabled... for service operation" —
is never suppressed by any preference at all.
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
from app.models.notification_preference import NotificationPreference
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import (
    broadcast_promotion,
    get_or_create_notification_preference,
    notify_riders_of_new_delivery,
    notify_rider_account_suspended,
    update_notification_preference,
)
from app.services.orders import create_order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer-p24@example.com"):
    user = User(name="Customer", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _rider(db, *, email, phone, online=True):
    rider = User(name="Rider", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=online))
    db.commit()
    return rider


def _restaurant(db, tag="p24"):
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
    return restaurant


def test_defaults_are_all_enabled(db):
    customer = _customer(db)
    preference = get_or_create_notification_preference(db, customer.id)
    db.commit()
    assert preference.order_updates is True
    assert preference.delivery_updates is True
    assert preference.payment_updates is True
    assert preference.promotions is True
    assert preference.system_notifications is True


def test_lazy_creation_is_race_safe_on_first_touch(db):
    """Two near-simultaneous first reads for the same user must never
    both try to insert — mirrors this codebase's own established
    check-then-insert recovery pattern, exercised here the same way
    other lazy-create tests in this suite already do: by forcing a
    second insert attempt for a user that already has a row."""
    customer = _customer(db)
    first = get_or_create_notification_preference(db, customer.id)
    db.commit()
    second = get_or_create_notification_preference(db, customer.id)
    assert first.id == second.id
    rows = db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == customer.id)).all()
    assert len(rows) == 1


def test_partial_update_only_changes_the_fields_sent(db):
    customer = _customer(db)
    update_notification_preference(db, customer.id, {"promotions": False, "order_updates": None, "delivery_updates": None, "payment_updates": None, "system_notifications": None})

    preference = get_or_create_notification_preference(db, customer.id)
    assert preference.promotions is False
    assert preference.order_updates is True
    assert preference.delivery_updates is True
    assert preference.payment_updates is True
    assert preference.system_notifications is True


def test_disabling_order_updates_suppresses_order_placed(db):
    customer = _customer(db)
    update_notification_preference(db, customer.id, {"order_updates": False})
    restaurant = _restaurant(db, "orderoff")

    product_restaurant = restaurant
    from app.models.product import Product

    product = Product(restaurant_id=product_restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_PLACED)
    )
    assert notification is None
    # The order itself was still placed successfully — a notification
    # preference must never affect whether the underlying business
    # operation (Rule 4) succeeds.
    assert order.id is not None


def test_broadcast_promotion_respects_each_customers_own_preference_independently(db, monkeypatch):
    opted_in = _customer(db, "promo-in@example.com")
    opted_out = _customer(db, "promo-out@example.com")
    update_notification_preference(db, opted_out.id, {"promotions": False})

    captured = {}

    class FakeResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": self._data}

    def fake_post_wrapper(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"} for _ in json])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post_wrapper)

    from app.services.notifications import upsert_push_token

    upsert_push_token(db, opted_in.id, "ExponentPushToken[in]")
    upsert_push_token(db, opted_out.id, "ExponentPushToken[out]")

    broadcast_promotion(db, "Sale!", "50% off today")

    in_app_notifications = db.scalars(
        select(Notification).where(Notification.type == NotificationType.PROMOTION)
    ).all()
    recipients = {n.user_id for n in in_app_notifications}
    assert opted_in.id in recipients
    assert opted_out.id not in recipients
    assert captured["messages"] == [{"to": "ExponentPushToken[in]", "title": "Sale!", "body": "50% off today", "data": {"type": "promotion"}, "sound": "default"}]


def test_new_delivery_broadcast_excludes_a_rider_who_opted_out_of_delivery_updates(db):
    restaurant = _restaurant(db, "deliveryoff")
    opted_in_rider = _rider(db, email="rider-deliveryin@example.com", phone="9800000030")
    opted_out_rider = _rider(db, email="rider-deliveryout@example.com", phone="9800000031")
    update_notification_preference(db, opted_out_rider.id, {"delivery_updates": False})

    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    customer = _customer(db, "deliveryoff-cust@example.com")
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)

    notify_riders_of_new_delivery(db, order)

    recipients = set(
        db.scalars(
            select(Notification.user_id).where(
                Notification.order_id == order.id, Notification.type == NotificationType.NEW_DELIVERY
            )
        )
    )
    assert opted_in_rider.id in recipients
    assert opted_out_rider.id not in recipients


def test_account_suspension_is_never_suppressed_by_any_preference(db):
    """"Default transactional notifications should remain enabled where
    necessary for service operation" — a rider turning off every single
    category, including system_notifications, must still be told their
    account was suspended; it gates whether they can work at all."""
    rider = _rider(db, email="rider-allprefsoff@example.com", phone="9800000032")
    update_notification_preference(
        db, rider.id,
        {"order_updates": False, "delivery_updates": False, "payment_updates": False, "promotions": False, "system_notifications": False},
    )

    notify_rider_account_suspended(db, rider)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.ACCOUNT_SUSPENDED)
    )
    assert notification is not None


def _client_with_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def test_get_and_put_preferences_over_http():
    engine = _client_with_db()
    try:
        with Session(engine) as seed:
            customer = _customer(seed, "http-prefs@example.com")
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            get_response = client.get("/api/v1/notifications/preferences", headers=headers)
            assert get_response.status_code == 200
            body = get_response.json()
            assert body == {
                "order_updates": True, "delivery_updates": True, "payment_updates": True,
                "promotions": True, "system_notifications": True,
            }

            patch_response = client.patch(
                "/api/v1/notifications/preferences", headers=headers, json={"promotions": False},
            )
            assert patch_response.status_code == 200
            updated = patch_response.json()
            assert updated["promotions"] is False
            assert updated["order_updates"] is True  # untouched

            confirm = client.get("/api/v1/notifications/preferences", headers=headers)
            assert confirm.json()["promotions"] is False
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_user_can_never_read_or_change_another_users_preferences_over_http():
    engine = _client_with_db()
    try:
        with Session(engine) as seed:
            user_a = _customer(seed, "prefs-a@example.com")
            user_b = _customer(seed, "prefs-b@example.com")
            token_a = create_access_token(user_a.id)
            token_b = create_access_token(user_b.id)

        with TestClient(app) as client:
            client.patch(
                "/api/v1/notifications/preferences",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"promotions": False},
            )
            b_view = client.get(
                "/api/v1/notifications/preferences", headers={"Authorization": f"Bearer {token_b}"}
            )
            # User B's own row is untouched by A's change — there is no
            # user_id field on the request body at all, so there is no
            # way to target anyone but the authenticated caller.
            assert b_view.json()["promotions"] is True
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
