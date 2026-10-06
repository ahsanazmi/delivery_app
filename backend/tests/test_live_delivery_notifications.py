"""Notifications & Communication System Phase 23 — Live Delivery
Notifications.

RIDER_ASSIGNED and RIDER_APPROACHING were already wired (Phase 12/20 and
Live Rider Tracking Phase 34 respectively) — confirmed, not re-tested
here; RIDER_APPROACHING's own existing docstring already documents the
two guards (OUT_FOR_DELIVERY-only, distance-gated, and a durable
already-notified check against the Notification table itself) that keep
it from ever firing per GPS update, exactly this phase's own explicit
requirement. The one genuine gap this phase's own audit found is
DELIVERY_COMPLETED for the restaurant owner — ORDER_DELIVERED already
notified the customer, but the restaurant, who may want the completion
(and, for COD, the cash handoff) confirmed, previously heard nothing.
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
from app.services.orders import create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant_with_owner(db, *, owner_email="owner-p23@example.com"):
    owner_phone = f"98{abs(hash(owner_email)) % 10**8:08d}"
    owner = User(name="Owner", email=owner_email, phone=owner_phone, password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Notif Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return owner, restaurant


def _place_order(db, restaurant, *, customer_email="customer-p23@example.com"):
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


def test_delivery_completed_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-delivered@example.com")
    customer, order = _place_order(db, restaurant, customer_email="cust-delivered@example.com")

    for target in (
        OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP,
        OrderStatus.RIDER_ASSIGNED, OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED,
    ):
        transition_order_status(db, order, target)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.ORDER_DELIVERED)
    )
    assert notification is not None
    assert notification.role == UserRole.RESTAURANT_OWNER
    assert notification.order_id == order.id

    # The customer's own copy of the same event still exists too — this
    # phase adds a second recipient, it never replaces the first.
    customer_notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.ORDER_DELIVERED)
    )
    assert customer_notification is not None
