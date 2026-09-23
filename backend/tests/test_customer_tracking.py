from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location
from app.services.tracking import get_order_tracking


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
        delivery_time_minutes=25,
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


def test_tracking_unassigned_before_rider_assigned(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["assignment_status"] == "unassigned"
    assert tracking["rider"] is None
    assert tracking["order_status"] == OrderStatus.PLACED
    assert tracking["estimated_delivery_at"] > order.created_at


def test_tracking_shows_rider_once_assigned(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    rider = User(name="Rider Bob", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    db.commit()
    assign_rider_to_order(db, order, rider.id)

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["assignment_status"] == "assigned"
    assert tracking["rider"].name == "Rider Bob"
    assert tracking["order_status"] == OrderStatus.RIDER_ASSIGNED


def test_rider_location_hidden_before_rider_assigned(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["rider_location"] is None


def test_rider_location_hidden_until_rider_reports_one(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    rider = User(name="Rider Bob", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["assignment_status"] == "assigned"
    assert tracking["rider_location"] is None  # rider hasn't reported a position yet


def test_rider_location_visible_once_assigned_and_reported(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    rider = User(name="Rider Bob", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    update_rider_location(db, rider, Decimal("12.9700"), Decimal("77.5900"))

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["rider_location"] is not None
    assert tracking["rider_location"]["latitude"] == pytest.approx(12.97)
    assert tracking["rider_location"]["longitude"] == pytest.approx(77.59)


def test_rider_location_hidden_again_after_delivery(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    rider = User(name="Rider Bob", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    update_rider_location(db, rider, Decimal("12.9700"), Decimal("77.5900"))
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)

    tracking = get_order_tracking(db, customer.id, order.id)
    assert tracking["order_status"] == OrderStatus.DELIVERED
    assert tracking["rider_location"] is None


def test_tracking_history_reflects_transitions(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    db.commit()

    tracking = get_order_tracking(db, customer.id, order.id)
    statuses = [entry.status for entry in tracking["status_history"]]
    assert statuses == [OrderStatus.PLACED, OrderStatus.CONFIRMED]


def test_customer_cannot_track_someone_elses_order(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    with pytest.raises(HTTPException) as exc_info:
        get_order_tracking(db, other.id, order.id)
    assert exc_info.value.status_code == 404


def test_tracking_endpoint_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            order = _place_order(seed, customer, restaurant)
            order_id = order.id
            from app.core.security import create_access_token

            token = create_access_token(customer.id)
            other_token = create_access_token(_customer(seed, email="other2@example.com").id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/customer/orders/{order_id}/tracking", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["order_status"] == "placed"
            assert body["assignment_status"] == "unassigned"
            assert body["rider"] is None
            assert body["rider_location"] is None
            assert len(body["status_history"]) == 1

            forbidden = client.get(
                f"/api/v1/customer/orders/{order_id}/tracking", headers={"Authorization": f"Bearer {other_token}"}
            )
            assert forbidden.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
