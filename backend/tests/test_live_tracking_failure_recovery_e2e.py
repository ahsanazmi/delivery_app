"""Live Rider Tracking Phase 38 — Failure End-to-End Test.

Most of this phase's 14 named scenarios are already covered by dedicated
unit/integration tests elsewhere, each doing the actual failure-injection
directly at the layer it belongs to:

- GPS unavailable -> test_tracking_failure_handling.py
  (test_a_rider_who_never_once_reports_gps_location_can_still_complete_a_full_delivery)
- WebSocket disconnect (client-side reconnect/backoff) -> customer-mobile's
  use-order-tracking.test.ts (Phase 20)
- rider loses internet (detection) -> rider-mobile's
  use-location-reporter.test.ts (Phase 25); recovery is automatic by the
  reporter's own stateless 12s-retry design (no special-case code exists
  to separately test — the very next tick just succeeds once the network
  is back)
- rider app backgrounded -> covered by real background tracking
  (rider-mobile/features/location/background-location-task.ts, predating
  this master command — see docs/live-tracking-architecture.md §11/§17);
  no server-side recovery code to test, since the backend just receives
  location updates from whichever path (foreground or background) sent
  them
- rider app killed -> no persistent client-side state to lose either way;
  a cold start after a normal kill is the same code path as the
  foreground reporter's own "goes through requesting-permission,
  starting, and tracking" test — a *hard* kill (force-stop, an aggressive
  OEM battery manager) dropping the background task specifically is a
  known, documented limitation (§11), not something fixed or fixable
  from this test
- duplicate GPS update -> test_rider_location.py's throttle tests (Phase 7)
- invalid coordinates -> test_rider_location_rejects_out_of_range_coordinates
- stale GPS timestamp -> test_an_implausible_timestamp_is_rejected
- large GPS jump -> test_an_implausible_gps_jump_with_poor_accuracy_is_rejected
- order cancelled / rider reassigned -> test_tracking_concurrency.py (Phase 31)
- delivery completed while connected -> test_live_tracking_e2e.py (Phase 37)

What's genuinely new here is END-TO-END *recovery* specifically — not
just "doesn't crash," but "the system comes back to a fully correct
state" — for the two scenarios that aren't naturally exercised by any
existing single-layer test: a customer's WebSocket dropping and later
reconnecting mid-delivery, and a server restart (this app's in-memory
state — the WS connection registry and the ETA cache — being wiped)
mid-delivery.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)

    def override_get_db():
        with Session(eng) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield eng
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(eng)


def _online_rider(db, *, email="rider@example.com", phone="8500000001"):
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


def test_customer_websocket_reconnect_fully_catches_up_on_everything_missed_while_disconnected(engine):
    """The customer's socket drops (simulated by closing it) right after
    the initial snapshot, and several real changes happen while it's
    down — a status transition, a rider assignment, and a GPS report.
    On reconnect, the fresh initial snapshot must reflect ALL of that,
    not just whatever the last live push before the drop happened to be
    — this is what makes it "recovery," not just "didn't crash while
    disconnected."""
    with Session(engine) as seed:
        customer = User(name="Cust", email="recover-customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        rider = _online_rider(seed)
        order_id, customer_id, rider_id = order.id, customer.id, rider.id
        token = create_access_token(customer_id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            snapshot = ws.receive_json()
            assert snapshot["order_status"] == "placed"
        # The `with` block exiting closes this connection — simulating the
        # customer's WebSocket dropping (backgrounded app, network loss).

        # Real changes happen while nobody is connected to watch them.
        with Session(engine) as worker:
            order = worker.get(type(order), order_id)
            transition_order_status(worker, order, OrderStatus.CONFIRMED)
            transition_order_status(worker, order, OrderStatus.PREPARING)
            transition_order_status(worker, order, OrderStatus.READY_FOR_PICKUP)
            assign_rider_to_order(worker, order, rider_id)
            transition_order_status(worker, order, OrderStatus.PICKED_UP)

        with Session(engine) as worker:
            worker_rider = worker.get(User, rider_id)
            update_rider_location(worker, worker_rider, Decimal("12.9750"), Decimal("77.5950"))

        # Reconnect ("recovery") — a brand new connection, same order.
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            caught_up = ws.receive_json()
            assert caught_up["order_status"] == "picked_up"
            assert caught_up["assignment_status"] == "assigned"
            assert caught_up["rider"]["id"] == str(rider_id)
            assert caught_up["rider_location"] is not None
            assert float(caught_up["rider_location"]["latitude"]) == pytest.approx(12.975)
            # Every transition that happened while disconnected is present,
            # not just the order's current status.
            statuses = [entry["status"] for entry in caught_up["status_history"]]
            assert statuses == ["placed", "confirmed", "preparing", "ready_for_pickup", "rider_assigned", "picked_up"]


def test_recovers_correctly_after_in_memory_state_is_wiped_simulating_a_server_restart(engine):
    """This app's WS connection registry and ETA cache are both in-process
    (see app/ws/manager.py's own docstring on this). A real process
    restart wipes both entirely. Everything a snapshot needs is re-read
    fresh from the database on every connect/broadcast (never from those
    caches alone) — simulate the wipe directly and confirm a fresh
    connection still gets a fully correct snapshot, proving the design
    doesn't secretly depend on anything surviving only in memory."""
    from app.services.eta import _eta_cache
    from app.ws.manager import manager

    with Session(engine) as seed:
        customer = User(name="Cust", email="restart-customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        rider = _online_rider(seed, email="restart-rider@example.com")
        order = seed.get(type(order), order.id)
        transition_order_status(seed, order, OrderStatus.CONFIRMED)
        transition_order_status(seed, order, OrderStatus.PREPARING)
        transition_order_status(seed, order, OrderStatus.READY_FOR_PICKUP)
        assign_rider_to_order(seed, order, rider.id)
        transition_order_status(seed, order, OrderStatus.PICKED_UP)
        transition_order_status(seed, order, OrderStatus.OUT_FOR_DELIVERY)
        order_id, customer_id, rider_id = order.id, customer.id, rider.id
        token = create_access_token(customer_id)

    with TestClient(app) as client:
        with Session(engine) as worker:
            worker_rider = worker.get(User, rider_id)
            update_rider_location(worker, worker_rider, Decimal("12.9750"), Decimal("77.5950"))

        # Simulate a full process restart: every in-memory structure this
        # subsystem owns is wiped, exactly as it would be on a real restart.
        manager._connections.clear()
        manager._pending.clear()
        _eta_cache.clear()

        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            snapshot = ws.receive_json()
            assert snapshot["order_status"] == "out_for_delivery"
            assert snapshot["rider_location"] is not None
            assert float(snapshot["rider_location"]["latitude"]) == pytest.approx(12.975)
            assert snapshot["estimated_delivery_at"] is not None
