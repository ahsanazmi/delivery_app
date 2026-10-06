"""Live Rider Tracking Phase 32 — Offline / Failure Handling.

Proves the master command's own standing rule in code: "live tracking is
auxiliary — if GPS/WebSocket/Maps fails, order processing must continue
unaffected," and specifically that a tracking-layer failure can never
corrupt order status, payment/COD, rider earnings, or assignment state.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.models.rider_earning import RiderEarning
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_deliveries import complete_delivery
from app.services.rider_location import update_rider_location
from app.services.routing import RouteUnavailableError


def _online_rider(db, *, email, phone):
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
        owner_id=owner.id,
        name="Chai House",
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("40.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _order_out_for_delivery(db, rider, *, payment_method="cod", customer_email="customer@example.com"):
    customer = User(name="Customer", email=customer_email, password_hash="x", role=UserRole.CUSTOMER)
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
    order = create_order(db, customer, address.id, payment_method=payment_method)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    if payment_method == "cod":
        order.is_paid = True
        db.commit()
    return order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_delivery_completes_correctly_even_when_the_routing_provider_is_completely_broken(db, monkeypatch):
    """The scenario this phase names "Google Routes unavailable" (OSRM
    here). A rider marking a delivery complete must still end up with a
    consistent order/assignment/earnings state even if the routing
    provider raises on every call — never a partially-applied delivery
    (order DELIVERED but assignment/earnings left stuck)."""
    rider = _online_rider(db, email="osrm-broken@example.com", phone="8100000001")
    order = _order_out_for_delivery(db, rider)
    order_id, rider_id = order.id, rider.id

    def _always_broken(*args, **kwargs):
        raise RouteUnavailableError("simulated total OSRM outage")

    monkeypatch.setattr("app.services.location_service.route", _always_broken)

    result = complete_delivery(db, rider, order_id)

    assert result.status == OrderStatus.DELIVERED
    assignment = db.scalar(select(DeliveryAssignment).where(DeliveryAssignment.order_id == order_id, DeliveryAssignment.rider_id == rider_id))
    assert assignment is not None
    assert assignment.status == AssignmentStatus.DELIVERED
    earning = db.scalar(select(RiderEarning).where(RiderEarning.order_id == order_id))
    assert earning is not None
    assert earning.amount == order.delivery_fee


def test_delivery_completes_correctly_even_when_the_tracking_broadcast_itself_raises(db, monkeypatch):
    """A failure completely unrelated to routing (e.g. a bug in the WS
    broadcast path itself) must be just as harmless — transition_order_status
    is the single choke point every status-changing caller goes through,
    so guarding it there protects complete_delivery (and every other
    caller) without each needing its own try/except."""
    rider = _online_rider(db, email="broadcast-broken@example.com", phone="8100000002")
    order = _order_out_for_delivery(db, rider)
    order_id, rider_id = order.id, rider.id

    def _always_broken(*args, **kwargs):
        raise RuntimeError("simulated WS manager internals bug")

    monkeypatch.setattr("app.services.orders.manager.broadcast", _always_broken)

    result = complete_delivery(db, rider, order_id)

    assert result.status == OrderStatus.DELIVERED
    assignment = db.scalar(select(DeliveryAssignment).where(DeliveryAssignment.order_id == order_id, DeliveryAssignment.rider_id == rider_id))
    assert assignment.status == AssignmentStatus.DELIVERED
    earning = db.scalar(select(RiderEarning).where(RiderEarning.order_id == order_id))
    assert earning is not None


def test_a_rider_who_never_once_reports_gps_location_can_still_complete_a_full_delivery(db):
    """GPS disabled / location permission revoked for the entire delivery.
    Order processing (accept through completion, including COD settlement
    and earnings) must not depend on live location ever having been
    reported at all."""
    rider = _online_rider(db, email="no-gps-ever@example.com", phone="8100000003")
    assert rider.current_latitude is None and rider.current_longitude is None

    order = _order_out_for_delivery(db, rider)
    order_id = order.id
    result = complete_delivery(db, rider, order_id)

    assert result.status == OrderStatus.DELIVERED
    assert result.is_paid is True
    db.refresh(rider)
    assert rider.current_latitude is None  # confirms this delivery truly never reported a position
    earning = db.scalar(select(RiderEarning).where(RiderEarning.order_id == order_id))
    assert earning is not None


def test_rider_location_update_still_saves_the_position_even_when_the_broadcast_fails(db, monkeypatch):
    """WebSocket unavailable / broken: the rider's own position must still
    be durably updated even though nobody could be notified live — a
    broadcast failure must degrade to "no live push," never "the update
    itself was rejected."""
    rider = _online_rider(db, email="ws-down@example.com", phone="8100000004")
    order = _order_out_for_delivery(db, rider, payment_method="online")
    rider_id = rider.id

    def _always_broken(*args, **kwargs):
        raise RuntimeError("simulated broadcast failure")

    # Phase 35's has_listeners optimization would otherwise skip the
    # broadcast entirely here (no real WS connection exists in this
    # service-layer test) — force it to actually attempt the broadcast so
    # this test genuinely exercises the failure path it's named for.
    monkeypatch.setattr("app.services.rider_location.manager.has_listeners", lambda order_id: True)
    monkeypatch.setattr("app.services.rider_location.manager.broadcast", _always_broken)

    result = update_rider_location(db, rider, Decimal("12.9701"), Decimal("77.5901"))

    assert float(result.latitude) == pytest.approx(12.9701)
    db.refresh(rider)
    assert float(rider.current_latitude) == pytest.approx(12.9701)
