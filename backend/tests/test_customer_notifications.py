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
from app.models.notification import NotificationType
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import list_notifications, mark_all_notifications_read, mark_notification_read
from app.services.orders import create_order, transition_order_status


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


def test_placing_order_notifies_order_placed_and_confirming_adds_order_confirmed(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    placed_notifications = list_notifications(db, customer.id)
    assert len(placed_notifications) == 1
    assert placed_notifications[0].type == NotificationType.ORDER_PLACED
    assert order.order_number in placed_notifications[0].body

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    db.commit()

    notifications = list_notifications(db, customer.id)
    assert len(notifications) == 2
    by_type = {n.type for n in notifications}
    assert by_type == {NotificationType.ORDER_PLACED, NotificationType.ORDER_CONFIRMED}
    confirmed = next(n for n in notifications if n.type == NotificationType.ORDER_CONFIRMED)
    assert order.order_number in confirmed.body
    assert confirmed.order_id == order.id
    assert confirmed.is_read is False


def test_cancelling_notifies_order_cancelled(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    transition_order_status(db, order, OrderStatus.CANCELLED, "Changed my mind")
    db.commit()

    notifications = list_notifications(db, customer.id)
    types = {n.type for n in notifications}
    assert NotificationType.ORDER_PLACED in types
    assert NotificationType.ORDER_CANCELLED in types


def test_pickup_notifies_order_picked_up(db):
    """Notification Event Integration (Phase 20) — the one status the
    customer previously heard nothing about between "a rider was assigned"
    and "it's out for delivery"."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    transition_order_status(db, order, OrderStatus.RIDER_ASSIGNED)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    db.commit()

    notifications = list_notifications(db, customer.id)
    picked_up = next((n for n in notifications if n.type == NotificationType.ORDER_PICKED_UP), None)
    assert picked_up is not None
    assert order.order_number in picked_up.body


def test_mark_notification_read(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    db.commit()

    notification = list_notifications(db, customer.id)[0]
    assert notification.is_read is False

    updated = mark_notification_read(db, customer.id, notification.id)
    assert updated.is_read is True


def test_cannot_mark_someone_elses_notification_read(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    db.commit()

    notification = list_notifications(db, customer.id)[0]
    with pytest.raises(HTTPException) as exc_info:
        mark_notification_read(db, other.id, notification.id)
    assert exc_info.value.status_code == 404


def test_mark_all_read(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    db.commit()

    assert all(not n.is_read for n in list_notifications(db, customer.id))
    updated_count = mark_all_notifications_read(db, customer.id)
    assert updated_count == 3  # placed, confirmed, preparing
    assert all(n.is_read for n in list_notifications(db, customer.id))


def test_notifications_endpoints_over_http():
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
            transition_order_status(seed, order, OrderStatus.CONFIRMED)
            seed.commit()
            from app.core.security import create_access_token

            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}

            listing = client.get("/api/v1/customer/notifications", headers=headers)
            assert listing.status_code == 200
            assert len(listing.json()) == 2  # placed, confirmed
            notification_id = listing.json()[0]["id"]
            assert listing.json()[0]["is_read"] is False

            read_one = client.post(f"/api/v1/customer/notifications/{notification_id}/read", headers=headers)
            assert read_one.status_code == 200
            assert read_one.json()["is_read"] is True

            read_all = client.post("/api/v1/customer/notifications/read-all", headers=headers)
            assert read_all.status_code == 200
            assert read_all.json()["updated"] == 1  # the other one; the first is already read
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
