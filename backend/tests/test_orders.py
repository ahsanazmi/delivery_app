from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.user import User, UserRole
from app.services.addresses import create_address, set_default_address
from app.services.cart import create_cart_for_user, upsert_item
from app.services.orders import create_order_from_cart


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_create_order_from_cart_builds_order_and_clears_cart():
    db = _db_session()
    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)

    upsert_item(db, cart, {
        "product_id": "prod-1",
        "restaurant_id": "rest-1",
        "product_name": "Masala Dosa",
        "unit_price": Decimal("120.00"),
        "quantity": 2,
    })
    upsert_item(db, cart, {
        "product_id": "prod-2",
        "restaurant_id": "rest-1",
        "product_name": "Filter Coffee",
        "unit_price": Decimal("60.00"),
        "quantity": 1,
    })

    order = create_order_from_cart(db, user_id, {
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "postal_code": "560001",
        "delivery_instructions": "Ring the bell",
    })

    assert order.total == Decimal("300.00")
    assert len(order.items) == 2
    assert order.status.value == "pending"
    assert db.query(type(cart)).count() == 1
    assert len(create_cart_for_user(db, user_id).items) == 0

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
