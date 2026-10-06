"""Live Rider Tracking Phase 34 — Notification Integration.

Covers the one genuinely new notification this phase introduces: "rider
is approaching," a proximity-triggered event evaluated on rider location
updates (see maybe_notify_rider_approaching in services/notifications.py),
distinct from the already-existing status-change notifications
(rider assigned / picked up / delivered), which this phase confirmed are
already wired via notify_order_status_change and needed no new code.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Notification, NotificationType, Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.notifications import maybe_notify_rider_approaching
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location

# The delivery address sits here; a rider a few meters away is "approaching,"
# one ~1.1km away (roughly one degree-of-latitude/100 in this region) is not.
DELIVERY_LAT = Decimal("12.9700")
DELIVERY_LNG = Decimal("77.5900")
NEARBY_LAT = Decimal("12.9705")
NEARBY_LNG = Decimal("77.5905")
FAR_LAT = Decimal("12.9800")
FAR_LNG = Decimal("77.6000")


def _online_rider(db, *, email="rider@example.com", phone="8200000001"):
    rider = User(name="Rider", email=email, password_hash="x", role=UserRole.RIDER, phone=phone)
    db.add(rider)
    db.commit()
    partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
    db.add(partner)
    db.commit()
    return rider


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


def _order_out_for_delivery(db, rider):
    customer = User(name="Customer", email="customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "latitude": DELIVERY_LAT, "longitude": DELIVERY_LNG,
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    return order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_fires_once_the_rider_is_within_range_while_out_for_delivery(db):
    rider = _online_rider(db)
    order = _order_out_for_delivery(db, rider)

    maybe_notify_rider_approaching(db, order, NEARBY_LAT, NEARBY_LNG)

    notification = db.scalar(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING))
    assert notification is not None
    assert notification.user_id == order.user_id


def test_does_not_fire_while_the_rider_is_still_far_away(db):
    rider = _online_rider(db)
    order = _order_out_for_delivery(db, rider)

    maybe_notify_rider_approaching(db, order, FAR_LAT, FAR_LNG)

    notification = db.scalar(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING))
    assert notification is None


def test_never_fires_before_out_for_delivery(db):
    """Assigned-and-nearby (e.g. the rider happens to start right next to
    the customer) must not be mistaken for "approaching" — only the
    OUT_FOR_DELIVERY leg counts."""
    rider = _online_rider(db)
    customer = User(name="Customer", email="c2@example.com", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "latitude": DELIVERY_LAT, "longitude": DELIVERY_LNG,
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)  # RIDER_ASSIGNED, not yet OUT_FOR_DELIVERY

    maybe_notify_rider_approaching(db, order, NEARBY_LAT, NEARBY_LNG)

    notification = db.scalar(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING))
    assert notification is None


def test_never_fires_a_second_time_for_the_same_order(db):
    """The exact requirement this phase is strictest about: "do not send a
    notification for every GPS update." Ten more updates inside range
    after the first must never create a second row."""
    rider = _online_rider(db)
    order = _order_out_for_delivery(db, rider)

    for _ in range(10):
        maybe_notify_rider_approaching(db, order, NEARBY_LAT, NEARBY_LNG)

    count = db.scalar(
        select(Notification.id).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING)
    )
    assert count is not None
    all_matches = list(db.scalars(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING)))
    assert len(all_matches) == 1


def test_wired_into_a_real_rider_location_update(db):
    """End-to-end through the actual call site: a rider PATCHing their
    location while OUT_FOR_DELIVERY and within range gets the customer a
    notification, with no separate wiring required."""
    rider = _online_rider(db)
    order = _order_out_for_delivery(db, rider)

    update_rider_location(db, rider, NEARBY_LAT, NEARBY_LNG)

    notification = db.scalar(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.RIDER_APPROACHING))
    assert notification is not None
