"""Notifications & Communication System Phase 40 — Failure Testing.

Most of this phase's own checklist was already proven by earlier
phases: push permission denied (Phase 16/28, client-side — no crash,
graceful null return), invalid/expired token (Phase 32), provider
unavailable/network unavailable (Phase 31's retry/backoff, eventual
"unknown," never raised to the caller), duplicate event/webhook retry
(Phase 18/30), app killed/restarted (Phase 29), expired authentication
(Phase 35), and the core "notification delivery raising never breaks
the business operation" guarantee itself (Phase 7's own dedicated
test_notification_service_failure_isolation.py). This file covers the
two genuinely untested scenarios this phase's own checklist names:
database unavailable (a real DB-level exception, not just an
application-level one, happening specifically during the notification's
own write) and tapping a notification tied to a long-settled/terminal
order.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer-p40@example.com"):
    user = User(name="Cust", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, tag="p40"):
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


def _place_order(db, customer, restaurant):
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
    return create_order(db, customer, address.id)


def test_order_status_transition_succeeds_even_when_the_database_itself_fails_mid_notification(db, monkeypatch):
    """A real sqlalchemy.exc.OperationalError (the actual exception type
    a dropped connection / unavailable database raises), not just a
    generic RuntimeError — raised from inside the notification's own
    SAVEPOINT, specifically at the push-dispatch call (which runs after
    the Notification row's own db.add). The business transition must
    still complete and commit."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    def fail_with_db_error(*args, **kwargs):
        raise OperationalError("statement", {}, Exception("server closed the connection unexpectedly"))

    monkeypatch.setattr("app.services.notifications.send_push_to_user", fail_with_db_error)

    result = transition_order_status(db, order, OrderStatus.CONFIRMED)

    assert result.status == OrderStatus.CONFIRMED
    with Session(db.get_bind()) as verify:
        persisted = verify.get(type(order), order.id)
        assert persisted.status == OrderStatus.CONFIRMED
        # The notification itself was correctly rolled back (the
        # SAVEPOINT undid it along with the failed push) — "notification
        # failure must not break business operations" never promised a
        # notification would still exist, only that the order would.
        rows = verify.scalars(select(Notification).where(Notification.order_id == order.id)).all()
        assert all(n.type.value != "order_confirmed" for n in rows)


def test_database_failure_during_the_notification_row_insert_itself_still_preserves_the_business_commit(db, monkeypatch):
    """A step earlier than the push dispatch: the database fails while
    the Notification row's own INSERT is being flushed, inside the same
    SAVEPOINT. Still must never surface to the caller."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    original_flush = Session.flush
    call_count = {"n": 0}

    def flaky_flush(self, *args, **kwargs):
        call_count["n"] += 1
        # Let every flush succeed except ones issued while inside the
        # notification's own nested transaction (identified by an active
        # SAVEPOINT) — simulates the database going away for exactly the
        # notification's own write, not the whole test setup before it.
        if self.in_nested_transaction():
            raise OperationalError("statement", {}, Exception("connection reset"))
        return original_flush(self, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", flaky_flush)

    result = transition_order_status(db, order, OrderStatus.CONFIRMED)

    assert result.status == OrderStatus.CONFIRMED
    with Session(db.get_bind()) as verify:
        persisted = verify.get(type(order), order.id)
        assert persisted.status == OrderStatus.CONFIRMED


def test_tapping_a_notification_for_a_long_settled_order_still_resolves_correctly(db):
    """"Notification tap with expired order" — this codebase never
    deletes an Order row, so there is no literal expiry; the realistic
    equivalent is a notification whose order has long since reached a
    terminal state. The authorized fetch a deep-link tap drives must
    still correctly resolve it, not error just because time has passed
    or the order is no longer "active"."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    for status in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
        transition_order_status(db, order, status)
    transition_order_status(db, order, OrderStatus.CANCELLED, "long settled")

    from app.services.orders import get_user_order

    resolved = get_user_order(db, customer.id, order.id)
    assert resolved is not None
    assert resolved.status == OrderStatus.CANCELLED

    notification = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.user_id == customer.id)
    )
    assert notification is not None
    assert notification.order_id == resolved.id
