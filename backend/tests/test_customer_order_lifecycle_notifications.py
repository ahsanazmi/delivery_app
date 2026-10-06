"""Notifications & Communication System Phase 18 — Customer Order
Notifications.

Every lifecycle event this phase's checklist names was already wired by
earlier phases (Admin Portal Phase 20's notify_order_placed /
_ORDER_STATUS_NOTIFICATIONS, in app/services/notifications.py) — this
file proves each of the ten fires the correct NotificationType for the
customer, and proves this phase's own explicit requirement ("avoid
duplicate notifications for repeated API requests") end to end: a
retried "place order" and a retried status transition each already
cannot succeed twice (create_order's cart-claim and
transition_order_status's conditional UPDATE, both from Phase 24's
"Database Transaction Testing" and Retry & Idempotency Integration), and
this file is what actually asserts that guarantee in terms of
Notification rows, not just order/status correctness — no prior test
checked the notification side of it.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.product import Product
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


def _customer(db, email="customer-p18@example.com"):
    user = User(name="Customer", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, tag="p18"):
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


def _order(db, customer, restaurant, tag="p18"):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("150.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": f"{tag} Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _notification_types_for(db, user_id) -> set[NotificationType]:
    return set(db.scalars(select(Notification.type).where(Notification.user_id == user_id)))


def test_every_lifecycle_event_through_normal_delivery_notifies_the_customer(db):
    customer = _customer(db, "happy-path@example.com")
    restaurant = _restaurant(db, "happy")
    order = _order(db, customer, restaurant, "happy")

    for status in (
        OrderStatus.CONFIRMED,
        OrderStatus.PREPARING,
        OrderStatus.RIDER_ASSIGNED,
        OrderStatus.PICKED_UP,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    ):
        transition_order_status(db, order, status)

    types = _notification_types_for(db, customer.id)
    assert types >= {
        NotificationType.ORDER_PLACED,
        NotificationType.ORDER_CONFIRMED,
        NotificationType.ORDER_PREPARING,
        NotificationType.RIDER_ASSIGNED,
        NotificationType.ORDER_PICKED_UP,
        NotificationType.ORDER_OUT_FOR_DELIVERY,
        NotificationType.ORDER_DELIVERED,
    }


def test_ready_for_pickup_notifies_the_customer(db):
    """A separate order/path — READY_FOR_PICKUP only ever precedes
    RIDER_ASSIGNED, so the happy-path walk above (which goes straight to
    RIDER_ASSIGNED, the more common real flow once a rider claims it
    quickly) never actually exercises it."""
    customer = _customer(db, "ready@example.com")
    restaurant = _restaurant(db, "ready")
    order = _order(db, customer, restaurant, "ready")

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    assert NotificationType.ORDER_READY in _notification_types_for(db, customer.id)


def test_cancelled_notifies_the_customer(db):
    customer = _customer(db, "cancel@example.com")
    restaurant = _restaurant(db, "cancel")
    order = _order(db, customer, restaurant, "cancel")

    transition_order_status(db, order, OrderStatus.CANCELLED, "customer changed their mind")

    assert NotificationType.ORDER_CANCELLED in _notification_types_for(db, customer.id)


def test_rejected_notifies_the_customer(db):
    customer = _customer(db, "reject@example.com")
    restaurant = _restaurant(db, "reject")
    order = _order(db, customer, restaurant, "reject")

    transition_order_status(db, order, OrderStatus.REJECTED, "restaurant is out of stock")

    assert NotificationType.ORDER_REJECTED in _notification_types_for(db, customer.id)


def test_retried_place_order_never_sends_a_second_order_placed_notification(db):
    """create_order's own cart-claim (an atomic conditional UPDATE) means a
    retried "Place Order" request — a double tap, or a client retry after
    a timeout, calling create_order() again for the exact same still-
    checked-out cart, with no new items added in between — can never
    create a second order from the same cart. This proves that guarantee
    in terms of notifications, not just orders: exactly one ORDER_PLACED
    row, never two."""
    customer = _customer(db, "retry-place@example.com")
    restaurant = _restaurant(db, "retryplace")
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("150.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "retryplace Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })

    order = create_order(db, customer, address.id)

    # The retry: the exact same call again, nothing else happened in
    # between (no fresh add_item) — the real shape of a client retry.
    with pytest.raises(ValueError, match="cart is empty"):
        create_order(db, customer, address.id)

    placed_notifications = db.scalars(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_PLACED)
    ).all()
    assert len(placed_notifications) == 1
    assert placed_notifications[0].order_id == order.id

    orders = db.scalars(select(Order).where(Order.user_id == customer.id)).all()
    assert len(orders) == 1


def test_retried_status_transition_never_sends_a_second_notification(db):
    """transition_order_status's own atomic conditional UPDATE (Database
    Transaction Testing, Phase 24) means a retried/duplicate transition
    request for a status this order has already moved past can never
    re-apply. This proves that guarantee in terms of notifications:
    exactly one ORDER_CONFIRMED row, never two, even though the retry is
    attempted."""
    customer = _customer(db, "retry-status@example.com")
    restaurant = _restaurant(db, "retrystatus")
    order = _order(db, customer, restaurant, "retrystatus")

    transition_order_status(db, order, OrderStatus.CONFIRMED)

    # A retried request for the exact same transition — CONFIRMED is no
    # longer a valid target from the order's own current (already-
    # CONFIRMED) status, so this must be rejected before ever reaching
    # notify_order_status_change again.
    with pytest.raises(ValueError, match="Cannot move an order"):
        transition_order_status(db, order, OrderStatus.CONFIRMED)

    confirmed_notifications = db.scalars(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_CONFIRMED)
    ).all()
    assert len(confirmed_notifications) == 1
