from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address, set_default_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_create_order_builds_order_and_clears_cart():
    db = _db_session()
    customer = User(name="Priya Customer", email="priya@example.com", password_hash="x", role=UserRole.CUSTOMER, phone="9998887777")
    db.add(customer)
    db.commit()

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
    dosa = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
    coffee = Product(restaurant_id=restaurant.id, name="Filter Coffee", price=Decimal("60.00"))
    db.add_all([dosa, coffee])
    db.commit()

    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, dosa.id, 2)
    add_item(db, cart, coffee.id, 1)

    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Priya Customer",
        "phone": "9998887777",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })

    order = create_order(db, customer, address.id, delivery_instructions="Ring the bell")

    assert order.total == Decimal("300.00")
    assert order.customer_name == "Priya Customer"
    assert order.customer_email == "priya@example.com"
    assert order.restaurant_name == "Chai House"
    assert len(order.items) == 2
    assert order.status.value == "placed"
    assert db.query(type(cart)).count() == 1
    assert len(create_cart_for_user(db, customer.id).items) == 0

    db.close()


def test_create_order_fails_when_cart_empty():
    db = _db_session()
    customer = User(name="Priya", email="priya2@example.com", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    create_cart_for_user(db, customer.id)
    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Priya",
        "phone": "9998887777",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })

    with pytest.raises(ValueError, match="cart is empty"):
        create_order(db, customer, address.id)

    db.close()


def test_create_and_default_address():
    db = _db_session()
    user = User(name="Test User", email="test@example.com", password_hash="hash", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()

    address = create_address(db, user.id, {
        "label": "Home",
        "recipient_name": "Test User",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "landmark": "Near bus stand",
        "latitude": Decimal("12.9716"),
        "longitude": Decimal("77.5946"),
    })

    assert address.is_default is True
    second = create_address(db, user.id, {
        "label": "Office",
        "recipient_name": "Test User",
        "phone": "9999999999",
        "address_line": "22 MG Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "landmark": "Near metro",
        "latitude": Decimal("12.9758"),
        "longitude": Decimal("77.5949"),
    })

    assert second.is_default is False
    set_default_address(db, user.id, second.id)
    assert address.is_default is False
    assert second.is_default is True

    db.close()
