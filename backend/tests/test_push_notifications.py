from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.models.push_token import PushToken
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import broadcast_promotion, upsert_push_token
from app.services.orders import create_order, transition_order_status
from app.services.push_notifications import send_push_to_user


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"data": self._data}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id,
        name="Chai House",
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, customer, restaurant):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_send_push_no_tokens_is_a_silent_noop(db, monkeypatch):
    customer = _customer(db)
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse([])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")
    assert called is False  # no tokens registered, so no network call at all


def test_send_push_calls_expo_with_registered_tokens(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[aaa]")

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["url"] = url
        captured["messages"] = json
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Order confirmed", "Your order is confirmed", data={"type": "order_status"})

    assert captured["url"] == "https://exp.host/--/api/v2/push/send"
    assert captured["messages"] == [
        {
            "to": "ExponentPushToken[aaa]",
            "title": "Order confirmed",
            "body": "Your order is confirmed",
            "data": {"type": "order_status"},
            "sound": "default",
        }
    ]


def test_stale_token_is_removed_on_device_not_registered(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[dead]")

    def fake_post(*args, **kwargs):
        return FakeResponse([{"status": "error", "details": {"error": "DeviceNotRegistered"}}])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")
    db.commit()

    remaining = db.query(PushToken).filter(PushToken.user_id == customer.id).all()
    assert remaining == []


def test_send_push_to_users_in_background_uses_its_own_independent_session(db, monkeypatch):
    """Performance & Reliability (Phase 39) — send_push_to_users_in_background()
    is what a scheduled BackgroundTask actually runs, potentially after
    the originating request's own db Session has already been torn down.
    It must never depend on being handed a session — it opens, uses, and
    commits an entirely independent one of its own (patched here to point
    at this test's own engine, since the real app engine has no schema
    created in this test process), and the stale-token cleanup
    send_push_to_users() itself never commits is still durably persisted
    even though there's no caller transaction to piggyback on."""
    from sqlalchemy.orm import sessionmaker

    from app.services import push_notifications

    customer = _customer(db, email="bgpush@example.com")
    upsert_push_token(db, customer.id, "ExponentPushToken[bg]")

    monkeypatch.setattr(
        "app.db.session.SessionLocal", sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    )

    def fake_post(*args, **kwargs):
        return FakeResponse([{"status": "error", "details": {"error": "DeviceNotRegistered"}}])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)

    push_notifications.send_push_to_users_in_background([customer.id], "Title", "Body")

    # A brand-new session against the same engine — never the `db`
    # fixture's own session object — proves the deletion was actually
    # committed by the background function itself, not left uncommitted
    # in a session only that function ever touched.
    with Session(db.get_bind()) as verify:
        remaining = verify.query(PushToken).filter(PushToken.user_id == customer.id).all()
        assert remaining == []


def test_network_failure_is_swallowed_and_does_not_raise(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[aaa]")

    def fake_post(*args, **kwargs):
        raise RuntimeError("network is down")

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")  # must not raise

    # the token survives - a transient network error doesn't mean the token is bad
    remaining = db.query(PushToken).filter(PushToken.user_id == customer.id).all()
    assert len(remaining) == 1


def test_order_status_change_triggers_push_with_deep_link_data(db, monkeypatch):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    upsert_push_token(db, customer.id, "ExponentPushToken[aaa]")

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    transition_order_status(db, order, OrderStatus.CONFIRMED)

    assert len(captured["messages"]) == 1
    message = captured["messages"][0]
    assert message["data"] == {"type": "order_status", "order_id": str(order.id), "status": "confirmed"}


def test_broadcast_promotion_notifies_only_active_customers(db, monkeypatch):
    active_customer = _customer(db, email="active@example.com")
    upsert_push_token(db, active_customer.id, "ExponentPushToken[active]")

    inactive_customer = _customer(db, email="inactive@example.com")
    inactive_customer.is_active = False
    db.commit()
    upsert_push_token(db, inactive_customer.id, "ExponentPushToken[inactive]")

    owner = User(name="Owner2", email="owner2@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    upsert_push_token(db, owner.id, "ExponentPushToken[owner]")

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"} for _ in json])

    monkeypatch.setattr("app.services.push_notifications.httpx.post", fake_post)
    notified = broadcast_promotion(db, "50% off!", "Today only")

    assert notified == 1
    assert len(captured["messages"]) == 1
    assert captured["messages"][0]["to"] == "ExponentPushToken[active]"

    from app.models.notification import Notification, NotificationType

    promo_notifications = db.query(Notification).filter(Notification.type == NotificationType.PROMOTION).all()
    assert len(promo_notifications) == 1
    assert promo_notifications[0].user_id == active_customer.id


def test_admin_broadcast_endpoint_requires_admin_role():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/admin/notifications/broadcast",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": "Sale!", "body": "Everything is 20% off."},
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_register_and_unregister_push_token_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)
            customer_id = customer.id

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            register = client.post(
                "/api/v1/notifications/register",
                headers=headers,
                json={"token": "ExponentPushToken[xyz]", "platform": "expo"},
            )
            assert register.status_code == 200

        with Session(engine) as check:
            assert check.query(PushToken).filter(PushToken.user_id == customer_id).count() == 1

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            unregister = client.request(
                "DELETE",
                "/api/v1/notifications/register",
                headers=headers,
                params={"token": "ExponentPushToken[xyz]"},
            )
            assert unregister.status_code == 204

        with Session(engine) as check:
            assert check.query(PushToken).filter(PushToken.user_id == customer_id).count() == 0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
