"""Notifications & Communication System Phase 33 — Rate Limiting /
Anti-Spam.

notify_admins now aggregates repeated alerts of the same type for the
same still-unread admin within a short window (one row, an occurrence
count, one push) instead of a brand new row and a brand new push per
event — "repeated admin alerts," this phase's own explicit example.
This file proves the aggregation itself, that it resets once the admin
actually reads the alert, that it's scoped per admin/per type (never
cross-contaminating), and — the explicit guardrail this phase names —
that it is never applied to a customer/rider/restaurant's own 1:1
transactional notification, each of which is about a different
person's own specific order.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import mark_notification_read, notify_admins
from app.services.orders import create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _admin(db, email="admin-p33@example.com"):
    admin = User(name="Admin", email=email, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    return admin


def _restaurant(db, tag="p33"):
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
    return restaurant


def _place_order(db, restaurant, *, customer_email="customer-p33@example.com"):
    customer = User(name="Cust", email=customer_email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
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
    return customer, create_order(db, customer, address.id)


def test_repeated_alerts_of_the_same_type_aggregate_into_one_unread_row(db):
    admin = _admin(db)
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Issue A", "First occurrence.")
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Issue B", "Second occurrence.")
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Issue C", "Third occurrence.")

    rows = db.scalars(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    ).all()
    assert len(rows) == 1  # never three separate rows
    assert rows[0].data["occurrences"] == 3
    assert "3 similar alerts" in rows[0].body
    assert "Third occurrence." in rows[0].body  # the most recent event's own body is still visible


def test_aggregation_never_crosses_notification_types(db):
    admin = _admin(db)
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "System issue.")
    notify_admins(db, NotificationType.ORDER_ISSUE, "Order issue", "Something about an order.")

    rows = db.scalars(select(Notification).where(Notification.user_id == admin.id)).all()
    assert len(rows) == 2
    assert {r.type for r in rows} == {NotificationType.SYSTEM_ALERT, NotificationType.ORDER_ISSUE}


def test_aggregation_never_crosses_admins(db):
    admin_a = _admin(db, "admin-a-p33@example.com")
    admin_b = _admin(db, "admin-b-p33@example.com")
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "Issue one.")
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "Issue two.")

    for admin in (admin_a, admin_b):
        rows = db.scalars(
            select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
        ).all()
        assert len(rows) == 1
        assert "2 similar alerts" in rows[0].body


def test_reading_the_aggregated_alert_lets_the_next_occurrence_start_fresh(db):
    admin = _admin(db)
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "Issue one.")
    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "Issue two.")

    existing = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    )
    mark_notification_read(db, admin.id, existing.id)

    notify_admins(db, NotificationType.SYSTEM_ALERT, "Alert", "Issue three (after the admin caught up).")

    rows = db.scalars(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    ).all()
    assert len(rows) == 2  # the read one, plus a genuinely fresh one
    unread = [r for r in rows if not r.is_read]
    assert len(unread) == 1
    assert unread[0].body == "Issue three (after the admin caught up)."


def test_customer_order_notifications_are_never_aggregated_even_when_many_happen_at_once(db):
    """This phase's own explicit guardrail: "never suppress critical
    transactional notifications simply because many events occurred."
    Ten different customers each placing and having their own order
    confirmed in quick succession must each get their own full set of
    notifications — these are ten different people's own specific
    orders, not a burst of one admin's operational noise."""
    restaurant = _restaurant(db, "burst")
    customers_and_orders = [
        _place_order(db, restaurant, customer_email=f"burst-{i}@example.com") for i in range(10)
    ]
    for customer, order in customers_and_orders:
        transition_order_status(db, order, OrderStatus.CONFIRMED)

    for customer, order in customers_and_orders:
        rows = db.scalars(
            select(Notification).where(
                Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_CONFIRMED
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].order_id == order.id
