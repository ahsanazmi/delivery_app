from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.reviews import check_review_eligibility


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


def test_nonexistent_order_is_not_eligible(db):
    customer = _customer(db)
    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, customer.id, customer.id)  # any UUID that isn't an order id
    assert exc_info.value.status_code == 404


def test_another_customers_order_is_not_eligible(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, other.id, order.id)
    assert exc_info.value.status_code == 404


def test_undelivered_order_is_not_eligible(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, customer.id, order.id)
    assert exc_info.value.status_code == 409


def test_cancelled_order_is_not_eligible(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CANCELLED)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, customer.id, order.id)
    assert exc_info.value.status_code == 409


def test_delivered_order_with_a_restaurant_is_eligible(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()

    eligible_order = check_review_eligibility(db, customer.id, order.id)
    assert eligible_order.id == order.id


def test_delivered_order_without_a_rider_is_not_eligible(db):
    # Order.rider_id has ondelete="SET NULL" — if the assigned rider's
    # account were ever deleted after delivery, rider_id on this otherwise
    # perfectly normal DELIVERED order would become NULL. Phase 11 requires
    # this to be caught explicitly, not silently stored as an orphaned
    # delivery_rating.
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    order.rider_id = None
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, customer.id, order.id)
    assert exc_info.value.status_code == 409


def test_delivered_order_without_a_restaurant_is_not_eligible(db):
    # Order.restaurant_id is nullable at the model level; even though the
    # normal checkout flow always populates it, this proves the eligibility
    # check verifies a reviewable target rather than assuming one exists.
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    order.restaurant_id = None
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        check_review_eligibility(db, customer.id, order.id)
    assert exc_info.value.status_code == 409
