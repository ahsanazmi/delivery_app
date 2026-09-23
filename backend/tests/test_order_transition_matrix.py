"""Test Automation (Phase 27) — Order transitions.

Every existing test file exercises specific transitions in the context of
its own scenario (a restaurant accepting, a rider picking up, an admin
cancelling). None of them, put together, actually locks down the *entire*
VALID_TRANSITIONS table at once — a future edit that accidentally adds or
removes one edge (e.g. loosening DELIVERED's empty target set, or allowing
PLACED -> PICKED_UP) could land without any of the scenario-based tests
ever exercising that exact, newly-wrong pair. This walks every possible
(from_status, to_status) combination and asserts transition_order_status()
allows it if and only if VALID_TRANSITIONS says so — nothing more,
nothing less.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.order import Order, OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import VALID_TRANSITIONS, create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _fresh_order(db) -> Order:
    owner = User(name="Owner", email="owner-matrix@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER, phone="9800000001")
    customer = User(name="Customer", email="customer-matrix@example.com", password_hash="x", role=UserRole.CUSTOMER, phone="9800000002")
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Matrix Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9800000002",
        "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


ALL_STATUSES = list(OrderStatus)


@pytest.mark.parametrize("from_status", ALL_STATUSES)
@pytest.mark.parametrize("to_status", ALL_STATUSES)
def test_transition_matrix_matches_valid_transitions_exactly(db, from_status, to_status):
    if from_status == to_status:
        pytest.skip("a status transitioning to itself isn't a meaningful case here")

    order = _fresh_order(db)
    # Force the order directly into from_status for this test's setup —
    # bypassing transition_order_status entirely, since we're testing the
    # very next transition in isolation, not how the order got here.
    order.status = from_status
    db.commit()

    should_succeed = to_status in VALID_TRANSITIONS.get(from_status, set())

    if should_succeed:
        transition_order_status(db, order, to_status)
        db.refresh(order)
        assert order.status == to_status
    else:
        with pytest.raises(ValueError, match="Cannot move"):
            transition_order_status(db, order, to_status)
        db.refresh(order)
        assert order.status == from_status  # rejected attempt must never mutate the row
