"""Restaurant Owner Portal — Phase 2: dashboard metrics."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
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
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.restaurant_dashboard import get_restaurant_dashboard, resolve_owner_restaurant


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


def _customer(db, email, phone):
    user = User(name="Customer", email=email, phone=phone, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _rider(db, email="rider@example.com", phone="9888888888"):
    user = User(name="Rider", email=email, phone=phone, password_hash="x", role=UserRole.RIDER)
    db.add(user)
    db.commit()
    return user


def _place_order(db, restaurant, price=Decimal("100.00"), suffix="0"):
    customer = _customer(db, email=f"cust{suffix}@example.com", phone=f"92{suffix.zfill(8)}")
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_dashboard_counts_orders_by_status_bucket(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    rider = _rider(db)

    placed = _place_order(db, restaurant, suffix="1")  # PLACED

    confirmed = _place_order(db, restaurant, suffix="2")
    transition_order_status(db, confirmed, OrderStatus.CONFIRMED)

    preparing = _place_order(db, restaurant, suffix="3")
    transition_order_status(db, preparing, OrderStatus.CONFIRMED)
    transition_order_status(db, preparing, OrderStatus.PREPARING)

    ready = _place_order(db, restaurant, suffix="4")
    transition_order_status(db, ready, OrderStatus.CONFIRMED)
    transition_order_status(db, ready, OrderStatus.PREPARING)
    transition_order_status(db, ready, OrderStatus.READY_FOR_PICKUP)

    out_for_delivery = _place_order(db, restaurant, suffix="5")
    transition_order_status(db, out_for_delivery, OrderStatus.CONFIRMED)
    transition_order_status(db, out_for_delivery, OrderStatus.PREPARING)
    transition_order_status(db, out_for_delivery, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, out_for_delivery, rider.id)
    transition_order_status(db, out_for_delivery, OrderStatus.PICKED_UP)
    transition_order_status(db, out_for_delivery, OrderStatus.OUT_FOR_DELIVERY)

    delivered = _place_order(db, restaurant, suffix="6")
    transition_order_status(db, delivered, OrderStatus.CONFIRMED)
    transition_order_status(db, delivered, OrderStatus.PREPARING)
    transition_order_status(db, delivered, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, delivered, rider.id)
    transition_order_status(db, delivered, OrderStatus.PICKED_UP)
    transition_order_status(db, delivered, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, delivered, OrderStatus.DELIVERED)

    cancelled = _place_order(db, restaurant, suffix="7")
    transition_order_status(db, cancelled, OrderStatus.CANCELLED)

    dashboard = get_restaurant_dashboard(db, restaurant)

    assert dashboard["pending_orders_count"] == 1  # placed
    assert dashboard["preparing_orders_count"] == 2  # confirmed + preparing
    assert dashboard["ready_orders_count"] == 2  # ready_for_pickup + out_for_delivery
    assert dashboard["completed_orders_count"] == 1  # delivered
    assert dashboard["today_orders_count"] == 7  # every order created just now, including cancelled


def test_today_sales_only_counts_delivered_orders(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    rider = _rider(db)

    delivered = _place_order(db, restaurant, price=Decimal("200.00"), suffix="1")
    transition_order_status(db, delivered, OrderStatus.CONFIRMED)
    transition_order_status(db, delivered, OrderStatus.PREPARING)
    transition_order_status(db, delivered, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, delivered, rider.id)
    transition_order_status(db, delivered, OrderStatus.PICKED_UP)
    transition_order_status(db, delivered, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, delivered, OrderStatus.DELIVERED)

    _place_order(db, restaurant, price=Decimal("500.00"), suffix="2")  # still PLACED — not sold yet

    dashboard = get_restaurant_dashboard(db, restaurant)
    assert dashboard["today_sales"] == Decimal("200.00")  # subtotal of the delivered order only


def test_pending_earnings_excludes_delivered_and_cancelled(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    rider = _rider(db)

    in_flight = _place_order(db, restaurant, price=Decimal("150.00"), suffix="1")  # PLACED

    delivered = _place_order(db, restaurant, price=Decimal("300.00"), suffix="2")
    transition_order_status(db, delivered, OrderStatus.CONFIRMED)
    transition_order_status(db, delivered, OrderStatus.PREPARING)
    transition_order_status(db, delivered, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, delivered, rider.id)
    transition_order_status(db, delivered, OrderStatus.PICKED_UP)
    transition_order_status(db, delivered, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, delivered, OrderStatus.DELIVERED)

    cancelled = _place_order(db, restaurant, price=Decimal("400.00"), suffix="3")
    transition_order_status(db, cancelled, OrderStatus.CANCELLED)

    dashboard = get_restaurant_dashboard(db, restaurant)
    assert dashboard["pending_earnings"] == Decimal("150.00")


def test_dashboard_scoped_to_this_restaurant_only(db):
    owner_a = _owner(db, email="ownera@example.com", phone="9111111111")
    owner_b = _owner(db, email="ownerb@example.com", phone="9222222222")
    restaurant_a = _restaurant(db, owner_a, name="A's Diner")
    restaurant_b = _restaurant(db, owner_b, name="B's Diner")

    _place_order(db, restaurant_a, price=Decimal("100.00"), suffix="1")
    _place_order(db, restaurant_b, price=Decimal("999.00"), suffix="2")
    _place_order(db, restaurant_b, price=Decimal("999.00"), suffix="3")

    dashboard = get_restaurant_dashboard(db, restaurant_a)
    assert dashboard["today_orders_count"] == 1
    assert dashboard["pending_orders_count"] == 1


def test_today_orders_excludes_orders_from_before_today(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)

    old_order = _place_order(db, restaurant, suffix="1")
    old_order.created_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()

    _place_order(db, restaurant, suffix="2")

    dashboard = get_restaurant_dashboard(db, restaurant)
    assert dashboard["today_orders_count"] == 1


def test_pending_orders_list_is_ordered_oldest_first(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)

    first = _place_order(db, restaurant, suffix="1")
    first.created_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    second = _place_order(db, restaurant, suffix="2")

    dashboard = get_restaurant_dashboard(db, restaurant)
    order_numbers = [o["order_number"] for o in dashboard["pending_orders"]]
    assert order_numbers == [first.order_number, second.order_number]


def test_resolve_owner_restaurant_defaults_to_sole_restaurant(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    resolved = resolve_owner_restaurant(db, owner, None)
    assert resolved.id == restaurant.id


def test_resolve_owner_restaurant_requires_id_with_multiple_restaurants(db):
    owner = _owner(db)
    _restaurant(db, owner, name="First")
    _restaurant(db, owner, name="Second")

    with pytest.raises(HTTPException) as exc:
        resolve_owner_restaurant(db, owner, None)
    assert exc.value.status_code == 400


def test_resolve_owner_restaurant_404_with_no_restaurant(db):
    owner = _owner(db)
    with pytest.raises(HTTPException) as exc:
        resolve_owner_restaurant(db, owner, None)
    assert exc.value.status_code == 404


def test_resolve_owner_restaurant_rejects_someone_elses_restaurant_id(db):
    owner_a = _owner(db, email="ownera2@example.com", phone="9333333333")
    owner_b = _owner(db, email="ownerb2@example.com", phone="9444444444")
    restaurant_b = _restaurant(db, owner_b, name="B's Diner")

    with pytest.raises(HTTPException) as exc:
        resolve_owner_restaurant(db, owner_a, restaurant_b.id)
    assert exc.value.status_code == 403


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


def test_dashboard_endpoint_over_http():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            _place_order(seed, restaurant, price=Decimal("120.00"), suffix="1")
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["restaurant_name"] == "Chai House"
            assert body["pending_orders_count"] == 1
            assert len(body["pending_orders"]) == 1
            assert len(body["recent_orders"]) == 1
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_restaurant_dashboard():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9555555555", password_hash="x", role=UserRole.CUSTOMER)
            rider = User(name="R", email="r@example.com", phone="9666666666", password_hash="x", role=UserRole.RIDER)
            seed.add_all([customer, rider])
            seed.commit()
            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)

        with TestClient(app) as client:
            assert client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {customer_token}"}
            ).status_code == 403
            assert client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {rider_token}"}
            ).status_code == 403
    finally:
        _teardown(engine)


def test_dashboard_endpoint_requires_restaurant_id_for_multi_restaurant_owner():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner, name="First")
            _restaurant(seed, owner, name="Second")
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 400
    finally:
        _teardown(engine)
