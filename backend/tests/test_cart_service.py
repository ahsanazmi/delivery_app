from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.cart import add_item, calculate_cart_totals, create_cart_for_user, sync_cart_with_catalog


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _restaurant(db, **overrides):
    owner = User(name="Owner", email=f"owner-{uuid4()}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    payload = {
        "owner_id": owner.id,
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("12.1"),
        "longitude": Decimal("77.1"),
        "minimum_order": Decimal("0.00"),
        "delivery_fee": Decimal("30.00"),
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    return restaurant


def test_cart_totals_and_single_merchant_rule():
    db = _db_session()
    restaurant = _restaurant(db)
    dosa = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
    tea = Product(restaurant_id=restaurant.id, name="Tea", price=Decimal("40.00"))
    db.add_all([dosa, tea])
    db.commit()

    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)
    add_item(db, cart, dosa.id, 2)
    add_item(db, cart, tea.id, 1)

    totals = calculate_cart_totals(db, cart)
    assert totals["subtotal"] == Decimal("280.00")
    assert totals["delivery_fee"] == Decimal("30.00")
    assert totals["total"] == Decimal("310.00")
    assert totals["total_items"] == 3
    assert cart.items[0].quantity == 2

    db.close()


def test_cart_rejects_item_from_different_merchant():
    db = _db_session()
    restaurant_a = _restaurant(db)
    restaurant_b = _restaurant(db)
    dosa = Product(restaurant_id=restaurant_a.id, name="Masala Dosa", price=Decimal("120.00"))
    burger = Product(restaurant_id=restaurant_b.id, name="Burger", price=Decimal("200.00"))
    db.add_all([dosa, burger])
    db.commit()

    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)
    add_item(db, cart, dosa.id, 1)

    with pytest.raises(ValueError, match="different restaurant"):
        add_item(db, cart, burger.id, 1)

    db.close()


def test_cart_rejects_unavailable_product():
    db = _db_session()
    restaurant = _restaurant(db)
    sold_out = Product(restaurant_id=restaurant.id, name="Sold Out Item", price=Decimal("50.00"), is_available=False)
    db.add(sold_out)
    db.commit()

    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)

    with pytest.raises(Exception):
        add_item(db, cart, sold_out.id, 1)

    db.close()


def test_sync_removes_items_that_became_unavailable_and_refreshes_price():
    db = _db_session()
    restaurant = _restaurant(db)
    dosa = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
    tea = Product(restaurant_id=restaurant.id, name="Tea", price=Decimal("40.00"))
    db.add_all([dosa, tea])
    db.commit()

    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)
    add_item(db, cart, dosa.id, 1)
    add_item(db, cart, tea.id, 1)

    # Price changes and one item goes out of stock, independent of what the cart has cached.
    dosa.price = Decimal("150.00")
    tea.is_available = False
    db.commit()

    removed = sync_cart_with_catalog(db, cart)
    assert removed == ["Tea"]
    assert len(cart.items) == 1
    assert cart.items[0].unit_price == Decimal("150.00")

    db.close()
