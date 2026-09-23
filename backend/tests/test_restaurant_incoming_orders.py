"""Restaurant Owner Portal — Phase 8: incoming orders."""

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
from app.services.orders import (
    assign_rider_to_order,
    create_order,
    mask_customer_name,
    transition_order_status,
)


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


def _rider(db, email="rider@example.com", phone="9888888888"):
    user = User(name="Rider", email=email, phone=phone, password_hash="x", role=UserRole.RIDER)
    db.add(user)
    db.commit()
    return user


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


def test_mask_customer_name():
    assert mask_customer_name("Amit Sharma") == "A**********"
    assert mask_customer_name("A") == "A"
    assert mask_customer_name("Bo") == "B*"


def test_list_orders_masks_customer_name(db):
    from app.services.orders import list_restaurant_orders

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    _place_order(db, restaurant, name="Amit Sharma", suffix="1")

    orders = list_restaurant_orders(db, restaurant.id)
    assert len(orders) == 1
    assert orders[0].customer_name == "Amit Sharma"  # raw model unaffected; masking happens at the schema/endpoint layer


def test_status_filter_buckets(db):
    from app.services.orders import list_restaurant_orders

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    rider = _rider(db)

    placed = _place_order(db, restaurant, suffix="1")  # pending

    confirmed = _place_order(db, restaurant, suffix="2")
    transition_order_status(db, confirmed, OrderStatus.CONFIRMED)

    preparing = _place_order(db, restaurant, suffix="3")
    transition_order_status(db, preparing, OrderStatus.CONFIRMED)
    transition_order_status(db, preparing, OrderStatus.PREPARING)

    ready = _place_order(db, restaurant, suffix="4")
    transition_order_status(db, ready, OrderStatus.CONFIRMED)
    transition_order_status(db, ready, OrderStatus.PREPARING)
    transition_order_status(db, ready, OrderStatus.READY_FOR_PICKUP)

    delivered = _place_order(db, restaurant, suffix="5")
    transition_order_status(db, delivered, OrderStatus.CONFIRMED)
    transition_order_status(db, delivered, OrderStatus.PREPARING)
    transition_order_status(db, delivered, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, delivered, rider.id)
    transition_order_status(db, delivered, OrderStatus.PICKED_UP)
    transition_order_status(db, delivered, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, delivered, OrderStatus.DELIVERED)

    cancelled = _place_order(db, restaurant, suffix="6")
    transition_order_status(db, cancelled, OrderStatus.CANCELLED)

    rejected = _place_order(db, restaurant, suffix="7")
    transition_order_status(db, rejected, OrderStatus.REJECTED)

    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="pending")} == {placed.id}
    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="confirmed")} == {confirmed.id}
    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="preparing")} == {preparing.id}
    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="ready")} == {ready.id}
    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="completed")} == {delivered.id}
    assert {o.id for o in list_restaurant_orders(db, restaurant.id, status_filter="cancelled")} == {cancelled.id, rejected.id}
    assert len(list_restaurant_orders(db, restaurant.id)) == 7  # no filter -> everything


def test_orders_scoped_to_this_restaurant_only(db):
    from app.services.orders import list_restaurant_orders

    owner_a = _owner(db, email="ownera@example.com", phone="9111111111")
    owner_b = _owner(db, email="ownerb@example.com", phone="9222222222")
    restaurant_a = _restaurant(db, owner_a, name="A's Diner")
    restaurant_b = _restaurant(db, owner_b, name="B's Diner")

    _place_order(db, restaurant_a, suffix="1")
    _place_order(db, restaurant_b, suffix="2")
    _place_order(db, restaurant_b, suffix="3")

    assert len(list_restaurant_orders(db, restaurant_a.id)) == 1
    assert len(list_restaurant_orders(db, restaurant_b.id)) == 2


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


def test_list_orders_endpoint_returns_masked_summary():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            _place_order(seed, restaurant, name="Amit Sharma", price=Decimal("450.00"), suffix="1")
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/orders", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            entry = body[0]
            assert entry["customer_name_masked"] == "A**********"
            assert "customer_name" not in entry  # the full name never appears in the list response
            assert entry["item_count"] == 1
            assert entry["total"] == "480.00"  # 450 + 30 delivery fee
            assert entry["payment_method"] == "cod"
            assert entry["status"] == "placed"
    finally:
        _teardown(engine)


def test_list_orders_endpoint_filters_by_status():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            _place_order(seed, restaurant, suffix="1")
            confirmed = _place_order(seed, restaurant, suffix="2")
            transition_order_status(seed, confirmed, OrderStatus.CONFIRMED)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/orders?status=confirmed", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["status"] == "confirmed"

            invalid = client.get(
                "/api/v1/restaurant/orders?status=not-a-real-status", headers={"Authorization": f"Bearer {token}"}
            )
            assert invalid.status_code == 422
    finally:
        _teardown(engine)


def test_order_detail_endpoint_shows_full_customer_and_delivery_info():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, name="Amit Sharma", suffix="1")
            order_id = order.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["customer_name"] == "Amit Sharma"  # full name in the detail view
            assert body["address_line"] == "15 Market Road"
            assert body["city"] == "Bengaluru"
            assert len(body["items"]) == 1
            assert body["items"][0]["quantity"] == 1
            assert "total" in body and "payment_method" in body and "created_at" in body
    finally:
        _teardown(engine)


def test_owner_cannot_see_or_open_another_owners_orders():
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
            headers = {"Authorization": f"Bearer {token_a}"}
            list_resp = client.get("/api/v1/restaurant/orders", headers=headers)
            assert list_resp.status_code == 200
            assert list_resp.json() == []  # owner A's own (empty) restaurant, not B's orders

            detail_resp = client.get(f"/api/v1/restaurant/orders/{order_b_id}", headers=headers)
            assert detail_resp.status_code == 404
    finally:
        _teardown(engine)


def test_owner_cannot_list_orders_via_another_owners_restaurant_id():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera3@example.com", phone="9555555555")
            owner_b = _owner(seed, email="ownerb3@example.com", phone="9666666666")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            restaurant_b_id = restaurant_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders?restaurant_id={restaurant_b_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_restaurant_order_endpoints():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9777777777", password_hash="x", role=UserRole.CUSTOMER)
            rider = User(name="R", email="r@example.com", phone="9888888887", password_hash="x", role=UserRole.RIDER)
            seed.add_all([customer, rider])
            seed.commit()
            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)

        with TestClient(app) as client:
            assert client.get(
                "/api/v1/restaurant/orders", headers={"Authorization": f"Bearer {customer_token}"}
            ).status_code == 403
            assert client.get(
                "/api/v1/restaurant/orders", headers={"Authorization": f"Bearer {rider_token}"}
            ).status_code == 403
    finally:
        _teardown(engine)
