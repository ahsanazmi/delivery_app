from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import Order, OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, list_user_orders, transition_order_status


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


def _place_order(db, customer, restaurant, product_name="Item"):
    product = Product(restaurant_id=restaurant.id, name=product_name, price=Decimal("100.00"))
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


def test_customer_only_sees_their_own_orders(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    _place_order(db, customer, restaurant)
    _place_order(db, other, restaurant, product_name="Other Item")

    results = list_user_orders(db, customer.id)
    assert len(results) == 1
    assert results[0].user_id == customer.id


def test_pagination_limits_and_offsets(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    for i in range(3):
        _place_order(db, customer, restaurant, product_name=f"Item {i}")

    page1 = list_user_orders(db, customer.id, offset=0, limit=2)
    page2 = list_user_orders(db, customer.id, offset=2, limit=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert {o.id for o in page1}.isdisjoint({o.id for o in page2})


def test_status_filter(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    placed = _place_order(db, customer, restaurant, product_name="Still Placed")
    to_cancel = _place_order(db, customer, restaurant, product_name="Will Cancel")
    transition_order_status(db, to_cancel, OrderStatus.CANCELLED)
    db.commit()

    active = list_user_orders(db, customer.id, status_filter=OrderStatus.PLACED)
    cancelled = list_user_orders(db, customer.id, status_filter=OrderStatus.CANCELLED)
    assert [o.id for o in active] == [placed.id]
    assert [o.id for o in cancelled] == [to_cancel.id]


def test_date_filter(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    far_past = datetime.now(timezone.utc) - timedelta(days=1)

    assert list_user_orders(db, customer.id, date_from=far_future) == []
    assert [o.id for o in list_user_orders(db, customer.id, date_from=far_past)] == [order.id]
    assert list_user_orders(db, customer.id, date_to=far_past) == []


def test_customer_order_history_endpoint_pagination_and_filters():
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
            for i in range(3):
                _place_order(seed, customer, restaurant, product_name=f"Item {i}")
            from app.core.security import create_access_token

            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            page1 = client.get("/api/v1/customer/orders", headers=headers, params={"page": 1, "limit": 2})
            assert page1.status_code == 200
            assert len(page1.json()) == 2

            page2 = client.get("/api/v1/customer/orders", headers=headers, params={"page": 2, "limit": 2})
            assert len(page2.json()) == 1

            filtered = client.get("/api/v1/customer/orders", headers=headers, params={"status": "placed"})
            assert filtered.status_code == 200
            assert len(filtered.json()) == 3

            filtered_none = client.get("/api/v1/customer/orders", headers=headers, params={"status": "delivered"})
            assert filtered_none.json() == []
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
