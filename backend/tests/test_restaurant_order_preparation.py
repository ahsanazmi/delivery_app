"""Restaurant Owner Portal — Phase 10: order preparation, Phase 11: ready for pickup."""

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
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, mark_order_preparing, mark_order_ready, transition_order_status


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


def _confirmed_order(db, restaurant, suffix="1"):
    order = _place_order(db, restaurant, suffix=suffix)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    return order


def test_mark_preparing_transitions_confirmed_to_preparing(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _confirmed_order(db, restaurant, suffix="1")

    updated = mark_order_preparing(db, restaurant.id, order.id)

    assert updated.status == OrderStatus.PREPARING


def test_mark_ready_transitions_preparing_to_ready(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _confirmed_order(db, restaurant, suffix="1")
    mark_order_preparing(db, restaurant.id, order.id)

    updated = mark_order_ready(db, restaurant.id, order.id)

    assert updated.status == OrderStatus.READY_FOR_PICKUP


def test_cannot_mark_preparing_from_placed(db):
    from fastapi import HTTPException

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, suffix="1")  # still PLACED, not accepted yet

    with pytest.raises(HTTPException) as exc:
        mark_order_preparing(db, restaurant.id, order.id)
    assert exc.value.status_code == 409


def test_cannot_mark_ready_from_confirmed(db):
    from fastapi import HTTPException

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _confirmed_order(db, restaurant, suffix="1")  # not yet PREPARING

    with pytest.raises(HTTPException) as exc:
        mark_order_ready(db, restaurant.id, order.id)
    assert exc.value.status_code == 409


def test_cannot_advance_another_restaurants_order(db):
    from fastapi import HTTPException

    owner_a = _owner(db, email="ownera@example.com", phone="9111111111")
    owner_b = _owner(db, email="ownerb@example.com", phone="9222222222")
    restaurant_a = _restaurant(db, owner_a, name="A's Diner")
    restaurant_b = _restaurant(db, owner_b, name="B's Diner")
    order_b = _confirmed_order(db, restaurant_b, suffix="1")

    with pytest.raises(HTTPException) as exc:
        mark_order_preparing(db, restaurant_a.id, order_b.id)
    assert exc.value.status_code == 404


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


def test_preparing_endpoint_advances_status():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _confirmed_order(seed, restaurant, suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/preparing", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "preparing"
    finally:
        _teardown(engine)


def test_ready_endpoint_advances_status():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _confirmed_order(seed, restaurant, suffix="1")
            transition_order_status(seed, order, OrderStatus.PREPARING)
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/ready", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "ready_for_pickup"
    finally:
        _teardown(engine)


def test_preparing_endpoint_rejects_wrong_stage_with_409():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")  # still placed
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/preparing", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 409
    finally:
        _teardown(engine)


def test_cannot_advance_another_owners_order_via_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera2@example.com", phone="9333333333")
            owner_b = _owner(seed, email="ownerb2@example.com", phone="9444444444")
            _restaurant(seed, owner_a, name="A's Diner")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            order_b = _confirmed_order(seed, restaurant_b, suffix="1")
            order_b_id = order_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/orders/{order_b_id}/preparing", headers={"Authorization": f"Bearer {token_a}"}
            )
            assert response.status_code == 404
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_advance_order_stage():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _confirmed_order(seed, restaurant, suffix="1")
            order_id = order.id
            customer = User(name="C", email="c@example.com", phone="9777777777", password_hash="x", role=UserRole.CUSTOMER)
            rider = User(name="R", email="r@example.com", phone="9888888887", password_hash="x", role=UserRole.RIDER)
            seed.add_all([customer, rider])
            seed.commit()
            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)

        with TestClient(app) as client:
            assert client.post(
                f"/api/v1/restaurant/orders/{order_id}/preparing", headers={"Authorization": f"Bearer {customer_token}"}
            ).status_code == 403
            assert client.post(
                f"/api/v1/restaurant/orders/{order_id}/ready", headers={"Authorization": f"Bearer {rider_token}"}
            ).status_code == 403
    finally:
        _teardown(engine)
