"""Notifications & Communication System Phase 26 — Read/Unread State.

mark_notification_read, mark_all_notifications_read, and
count_unread_notifications already existed (Phase 9) and were already
correct — this file is what was actually missing: explicit proof that a
duplicate read operation (a double-tap, a retried request) never raises
and never corrupts state, and that unread count is always derived fresh
from the server's own is_read column, never trusted from a client.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import (
    count_unread_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.services.orders import create_order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer_with_notifications(db, tag="p26"):
    customer = User(name="Cust", email=f"customer-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    create_order(db, customer, address.id)  # raises ORDER_PLACED
    return customer


def test_marking_the_same_notification_read_twice_never_errors(db):
    customer = _customer_with_notifications(db, "doubletap")
    notification = list_notifications(db, customer.id)[0]

    first = mark_notification_read(db, customer.id, notification.id)
    second = mark_notification_read(db, customer.id, notification.id)  # a double-tap / retried request

    assert first.is_read is True
    assert second.is_read is True
    assert second.read_at == first.read_at  # the original timestamp is never overwritten


def test_marking_all_read_twice_never_errors_and_the_second_call_updates_nothing(db):
    customer = _customer_with_notifications(db, "doublemarkall")

    first_count = mark_all_notifications_read(db, customer.id)
    second_count = mark_all_notifications_read(db, customer.id)  # a retried request

    assert first_count == 1
    assert second_count == 0
    assert count_unread_notifications(db, customer.id) == 0


def test_unread_count_is_always_derived_fresh_never_cached_on_the_notification_list(db):
    """Server-side state is authoritative — count_unread_notifications is
    its own direct query, not a client-maintained running total that
    could drift from what mark_notification_read actually persisted."""
    customer = _customer_with_notifications(db, "freshcount")
    assert count_unread_notifications(db, customer.id) == 1

    notification = list_notifications(db, customer.id)[0]
    mark_notification_read(db, customer.id, notification.id)
    assert count_unread_notifications(db, customer.id) == 0

    # Marking it read again (duplicate op) must never make the count go
    # negative or otherwise drift.
    mark_notification_read(db, customer.id, notification.id)
    assert count_unread_notifications(db, customer.id) == 0
