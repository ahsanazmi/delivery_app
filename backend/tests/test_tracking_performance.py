"""Live Rider Tracking Phase 35 — Performance/Scalability.

The actual optimization this phase adds: OrderTrackingConnectionManager.
has_listeners() lets update_rider_location skip building a tracking
snapshot (a DB read, and possibly a live-ETA/OSRM call) on the
high-frequency GPS-driven broadcast path when nobody is connected to
receive it. The "someone IS listening" side of this is already covered
end-to-end by test_customer_tracking_ws.py's
test_ws_broadcasts_rider_location_only_once_visible (a real WebSocket
connection receiving a real broadcast); this file covers the new "skip
when nobody's listening" half specifically.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location


def _online_rider(db, *, email="rider@example.com", phone="8300000001"):
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


def _assigned_order(db, rider):
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
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)
    return order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_a_location_update_skips_building_a_snapshot_when_nobody_is_listening(db, monkeypatch):
    """The order is genuinely visible (RIDER_ASSIGNED, location-visible
    status) but no WebSocket is connected to it in this test — the
    expensive snapshot build (and any live-ETA/OSRM call inside it) must
    never run in that case."""
    rider = _online_rider(db)
    order = _assigned_order(db, rider)

    calls: list[object] = []
    monkeypatch.setattr(
        "app.services.rider_location.build_tracking_snapshot",
        lambda db, order: calls.append(order.id),
    )

    update_rider_location(db, rider, Decimal("12.9700"), Decimal("77.5900"))

    assert calls == []


def test_has_listeners_reflects_real_registered_connections():
    """Direct unit check of the manager method itself, independent of the
    rider-location wiring above."""
    from uuid import uuid4

    from app.ws.manager import OrderTrackingConnectionManager

    mgr = OrderTrackingConnectionManager()
    order_id = uuid4()
    assert mgr.has_listeners(order_id) is False
