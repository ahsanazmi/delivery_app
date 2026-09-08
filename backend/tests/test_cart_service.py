from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.cart import Cart, CartItem
from app.services.cart import calculate_cart_totals, create_cart_for_user, upsert_item


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_cart_totals_and_single_merchant_rule():
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
        "product_name": "Tea",
        "unit_price": Decimal("40.00"),
        "quantity": 1,
    })

    totals = calculate_cart_totals(cart)
    assert totals["subtotal"] == Decimal("280.00")
    assert totals["total_items"] == 3
    assert cart.items[0].quantity == 2

    db.close()


def test_cart_rejects_item_from_different_merchant():
    db = _db_session()
    user_id = uuid4()
    cart = create_cart_for_user(db, user_id)

    upsert_item(db, cart, {
        "product_id": "prod-1",
        "restaurant_id": "rest-1",
        "product_name": "Masala Dosa",
        "unit_price": Decimal("120.00"),
        "quantity": 1,
    })

    try:
        upsert_item(db, cart, {
            "product_id": "prod-2",
            "restaurant_id": "rest-2",
            "product_name": "Burger",
            "unit_price": Decimal("200.00"),
            "quantity": 1,
        })
        assert False, "Expected ValueError for different restaurant"
    except ValueError:
        pass

    db.close()
