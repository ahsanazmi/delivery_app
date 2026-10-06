"""Notifications & Communication System Phase 7 — Notification Service,
"handle failure."

Proves the real correctness fix this phase makes, not just a refactor:
several notify_* functions are called BEFORE their caller's own
db.commit() (transition_order_status, in particular). Before this phase,
an unhandled exception inside notification delivery would corrupt the
caller's own still-uncommitted business transaction — this file proves
that's no longer possible, using a real SAVEPOINT-backed failure
boundary rather than a bare try/except.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import list_notifications
from app.services.orders import create_order, transition_order_status


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
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
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
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_order_status_transition_succeeds_even_when_notification_delivery_raises(db, monkeypatch):
    """The core claim: transition_order_status must complete and commit
    the status change, and must never raise, even when something inside
    the notification pipeline (here: the push dispatch call) throws an
    unhandled exception."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    monkeypatch.setattr(
        "app.services.notifications.send_push_to_user",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated push provider crash")),
    )

    result = transition_order_status(db, order, OrderStatus.CONFIRMED)

    assert result.status == OrderStatus.CONFIRMED
    with Session(db.get_bind()) as verify:
        persisted = verify.get(type(order), order.id)
        assert persisted.status == OrderStatus.CONFIRMED


def test_a_failed_notification_leaves_no_partial_row_and_does_not_poison_the_session(db, monkeypatch):
    """Beyond "doesn't raise": the savepoint rollback must mean (a) no
    half-written Notification row exists for the failed attempt, and
    (b) the session is still perfectly usable afterward for the caller's
    own subsequent work (proving the rollback was scoped to just the
    notification's own savepoint, not something that corrupted the wider
    session state)."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    monkeypatch.setattr(
        "app.services.notifications.send_push_to_user",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated push provider crash")),
    )

    transition_order_status(db, order, OrderStatus.CONFIRMED)

    confirmed_notification = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.ORDER_CONFIRMED)
    )
    assert confirmed_notification is None, "a failed notification attempt must never leave a partial row behind"

    # The session must still be fully usable — proves the savepoint
    # rollback didn't poison anything beyond its own scope.
    monkeypatch.undo()
    result = transition_order_status(db, order, OrderStatus.PREPARING)
    assert result.status == OrderStatus.PREPARING
    preparing_notification = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.ORDER_PREPARING)
    )
    assert preparing_notification is not None


def test_two_independent_notifications_in_one_call_are_isolated_from_each_other(db, monkeypatch):
    """notify_order_status_change can raise two separate notifications in
    one call (the customer's own + the rider's cancellation alert) — one
    failing must never prevent the other from being attempted."""
    from app.services.orders import assign_rider_to_order

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()
    for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP, OrderStatus.RIDER_ASSIGNED):
        if target == OrderStatus.RIDER_ASSIGNED:
            assign_rider_to_order(db, order, rider.id)
        else:
            transition_order_status(db, order, target)

    real_send = __import__("app.services.push_notifications", fromlist=["send_push_to_user"]).send_push_to_user

    def _fail_only_for_customer(db_, user_id, *args, **kwargs):
        if user_id == customer.id:
            raise RuntimeError("simulated failure for the customer notification specifically")
        return real_send(db_, user_id, *args, **kwargs)

    monkeypatch.setattr("app.services.notifications.send_push_to_user", _fail_only_for_customer)

    transition_order_status(db, order, OrderStatus.CANCELLED, "customer changed their mind")

    customer_cancelled = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.ORDER_CANCELLED)
    )
    rider_cancelled = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.DELIVERY_CANCELLED)
    )
    assert customer_cancelled is None, "the customer's own notification failed and must be rolled back"
    assert rider_cancelled is not None, "the rider's separate notification must still have succeeded"


def test_notify_admins_rejects_a_non_admin_notification_type():
    """"Validate notification type" — a caller passing a customer/rider-
    facing type to the admin broadcast function is a real bug, not an
    external failure, and must raise loudly rather than being silently
    swallowed by the failure boundary."""
    from app.services.notifications import notify_admins

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError):
                notify_admins(db, NotificationType.ORDER_CONFIRMED, "wrong type", "should never be accepted")
    finally:
        Base.metadata.drop_all(engine)
