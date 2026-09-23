"""Restaurant Owner Portal — Phase 9: accept / reject orders."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Notification, Product, Restaurant, User, UserRole
from app.models.notification import NotificationType
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import accept_order, create_order, reject_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com", phone="9000000001"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House"):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, name="Amit Sharma", price=Decimal("100.00"), suffix="1"):
    customer = User(name=name, email=f"cust{suffix}@example.com", phone=f"92{suffix.zfill(8)}", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": name, "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_accept_order_transitions_placed_to_confirmed(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")

    accepted = accept_order(db, restaurant.id, order.id)

    assert accepted.status == OrderStatus.CONFIRMED


def test_reject_order_transitions_placed_to_rejected_and_stores_reason(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")

    rejected = reject_order(db, restaurant.id, order.id, "Out of stock")

    assert rejected.status == OrderStatus.REJECTED
    assert rejected.cancelled_reason == "Out of stock"


def test_reject_order_without_a_reason_still_succeeds(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")

    rejected = reject_order(db, restaurant.id, order.id)

    assert rejected.status == OrderStatus.REJECTED
    assert rejected.cancelled_reason is None


def test_reject_notifies_the_customer(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")

    reject_order(db, restaurant.id, order.id, "Kitchen closed early")

    notification = (
        db.query(Notification)
        .filter(Notification.user_id == order.user_id, Notification.type == NotificationType.ORDER_REJECTED)
        .first()
    )
    assert notification is not None
    assert order.order_number in notification.body


def test_cannot_accept_or_reject_an_already_cancelled_order(db):
    from fastapi import HTTPException

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")
    transition_order_status(db, order, OrderStatus.CANCELLED)

    with pytest.raises(HTTPException) as accept_exc:
        accept_order(db, restaurant.id, order.id)
    assert accept_exc.value.status_code == 409

    with pytest.raises(HTTPException) as reject_exc:
        reject_order(db, restaurant.id, order.id)
    assert reject_exc.value.status_code == 409


def test_cannot_accept_or_reject_another_restaurants_order(db):
    from fastapi import HTTPException

    owner_a = _owner(db, email="ownera@example.com", phone="9111111111")
    owner_b = _owner(db, email="ownerb@example.com", phone="9222222222")
    restaurant_a = _restaurant(db, owner_a, name="A's Diner")
    restaurant_b = _restaurant(db, owner_b, name="B's Diner")
    order_b = _place_order(db, restaurant_b, suffix="1")

    with pytest.raises(HTTPException) as accept_exc:
        accept_order(db, restaurant_a.id, order_b.id)
    assert accept_exc.value.status_code == 404

    with pytest.raises(HTTPException) as reject_exc:
        reject_order(db, restaurant_a.id, order_b.id)
    assert reject_exc.value.status_code == 404


def _http_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def _teardown(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_accept_endpoint_confirms_the_order():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/accept", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "confirmed"
    finally:
        _teardown(engine)


def test_double_click_accept_the_second_call_is_a_clean_409_not_a_double_confirmation():
    """Integration Phase 16 — "Restaurant accepts order twice": the second
    call must not silently succeed again or create a second status-history
    entry; VALID_TRANSITIONS[CONFIRMED] doesn't include CONFIRMED, so it's
    a clean 409 and the order is left exactly as the first, real accept
    left it."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            first = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=headers)
            assert first.status_code == 200
            assert first.json()["status"] == "confirmed"

            second = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=headers)
            assert second.status_code == 409

            detail = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=headers)
            assert detail.json()["status"] == "confirmed"
            assert len(detail.json()["status_history"]) == 2  # placed, confirmed — not a third entry
    finally:
        _teardown(engine)


def test_reject_endpoint_accepts_optional_reason():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/reject",
                headers={"Authorization": f"Bearer {token}"},
                json={"reason": "No delivery riders available"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "rejected"
            assert body["cancelled_reason"] == "No delivery riders available"
    finally:
        _teardown(engine)


def test_reject_endpoint_works_with_no_body_at_all():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/reject", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "rejected"
    finally:
        _teardown(engine)


def test_accept_endpoint_rejects_already_terminal_order_with_409():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            transition_order_status(seed, order, OrderStatus.CANCELLED)
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/accept", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 409
    finally:
        _teardown(engine)


def test_cannot_accept_another_owners_order_via_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera2@example.com", phone="9333333333")
            owner_b = _owner(seed, email="ownerb2@example.com", phone="9444444444")
            _restaurant(seed, owner_a, name="A's Diner")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            order_b = _place_order(seed, restaurant_b, suffix="1")
            order_b_id = order_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_b_id}/accept", headers={"Authorization": f"Bearer {token_a}"}
            )
            assert response.status_code == 404
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_accept_or_reject_orders():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            customer = User(name="C", email="c@example.com", phone="9777777777", password_hash="x", role=UserRole.CUSTOMER)
            rider = User(name="R", email="r@example.com", phone="9888888887", password_hash="x", role=UserRole.RIDER)
            seed.add_all([customer, rider])
            seed.commit()
            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)

        with TestClient(app) as client:
            assert client.post(
                f"/api/v1/restaurant/orders/{order_id}/accept", headers={"Authorization": f"Bearer {customer_token}"}
            ).status_code == 403
            assert client.post(
                f"/api/v1/restaurant/orders/{order_id}/reject", headers={"Authorization": f"Bearer {rider_token}"}
            ).status_code == 403
    finally:
        _teardown(engine)
