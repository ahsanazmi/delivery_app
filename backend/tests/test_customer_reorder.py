from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user, get_cart_for_user
from app.services.orders import create_order, reorder_from_order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com", phone="9999999999"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER, phone=phone)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, **overrides):
    owner = User(name="Owner", email=f"owner-{overrides.get('name','x')}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
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
        "is_active": True,
        "is_open": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    return restaurant


def _address(db, user):
    return create_address(db, user.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })


def _placed_order(db, customer, restaurant, product, quantity=1):
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, quantity)
    address = _address(db, customer)
    return create_order(db, customer, address.id)


def test_reorder_adds_items_to_cart_at_current_price(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    order = _placed_order(db, customer, restaurant, product, quantity=2)

    # Price goes up after the order was placed.
    product.price = Decimal("260.00")
    db.commit()

    result = reorder_from_order(db, customer, order.id)
    assert result["unavailable_items"] == []

    cart = get_cart_for_user(db, customer.id)
    assert len(cart.items) == 1
    assert cart.items[0].quantity == 2
    assert cart.items[0].unit_price == Decimal("260.00")  # current price, not order's 220.00


def test_reorder_skips_deactivated_product(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    order = _placed_order(db, customer, restaurant, product)

    product.is_active = False
    db.commit()

    result = reorder_from_order(db, customer, order.id)
    assert result["unavailable_items"] == ["Biryani"]
    cart = get_cart_for_user(db, customer.id)
    assert cart.items == []


def test_reorder_skips_unavailable_product(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    order = _placed_order(db, customer, restaurant, product)

    product.is_available = False
    db.commit()

    result = reorder_from_order(db, customer, order.id)
    assert result["unavailable_items"] == ["Biryani"]


def test_reorder_rejects_when_restaurant_closed_down(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    order = _placed_order(db, customer, restaurant, product)

    restaurant.is_active = False
    db.commit()

    with pytest.raises(HTTPException) as exc:
        reorder_from_order(db, customer, order.id)
    assert exc.value.status_code == 409
    assert "no longer available" in exc.value.detail


def test_reorder_partial_availability_reports_unavailable_items(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    biryani = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    naan = Product(restaurant_id=restaurant.id, name="Naan", price=Decimal("40.00"))
    db.add_all([biryani, naan])
    db.commit()

    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, biryani.id, 1)
    add_item(db, cart, naan.id, 2)
    address = _address(db, customer)
    order = create_order(db, customer, address.id)

    naan.is_active = False
    db.commit()

    result = reorder_from_order(db, customer, order.id)
    assert result["unavailable_items"] == ["Naan"]
    cart = get_cart_for_user(db, customer.id)
    assert len(cart.items) == 1
    assert cart.items[0].product_name == "Biryani"


def test_reorder_rejects_when_cart_has_different_restaurant(db):
    customer = _customer(db)
    restaurant_a = _restaurant(db, name="Restaurant A")
    product_a = Product(restaurant_id=restaurant_a.id, name="Biryani", price=Decimal("220.00"))
    db.add(product_a)
    db.commit()
    order = _placed_order(db, customer, restaurant_a, product_a)

    restaurant_b = _restaurant(db, name="Restaurant B")
    product_b = Product(restaurant_id=restaurant_b.id, name="Dosa", price=Decimal("90.00"))
    db.add(product_b)
    db.commit()
    cart = get_cart_for_user(db, customer.id)
    add_item(db, cart, product_b.id, 1)

    with pytest.raises(HTTPException) as exc:
        reorder_from_order(db, customer, order.id)
    assert exc.value.status_code == 409
    assert "different restaurant" in exc.value.detail


def test_reorder_nonexistent_order_returns_404(db):
    customer = _customer(db)
    import uuid

    with pytest.raises(HTTPException) as exc:
        reorder_from_order(db, customer, uuid.uuid4())
    assert exc.value.status_code == 404


def test_reorder_does_not_recreate_order_only_populates_cart(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()
    order = _placed_order(db, customer, restaurant, product)

    from app.models.order import Order

    orders_before = db.query(Order).count()
    reorder_from_order(db, customer, order.id)
    orders_after = db.query(Order).count()
    assert orders_before == orders_after == 1
