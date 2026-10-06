"""Live Rider Tracking Phase 31 — Concurrency Testing.

Covers the phase's four named scenarios: (1) the same rider sending
multiple simultaneous location updates, (2) a delivery ending while a
location update is in flight, (3) a rider being reassigned while their
own connection/session is still active, and (4) confirming a stale
connection cannot continue broadcasting once its room is closed.
"""

import asyncio
import threading
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.models.rider_location import RiderLocationPing
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import admin_reassign_rider, assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location
from app.ws.manager import OrderTrackingConnectionManager


def _rider(db, *, email, phone):
    rider = User(name="Rider", email=email, password_hash="x", role=UserRole.RIDER, phone=phone)
    db.add(rider)
    db.commit()
    return rider


def _online_rider(db, *, email, phone):
    rider = _rider(db, email=email, phone=phone)
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
        delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _assigned_order(db, rider, *, customer_email="customer@example.com"):
    """An order carried through to RIDER_ASSIGNED — the state in which its
    rider's location becomes broadcast-visible."""
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
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)
    return order


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False, "timeout": 30}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


def test_same_rider_concurrent_location_updates_do_not_corrupt_state(tmp_path):
    """Several near-simultaneous updates for the same online rider, each on
    its own DB session/thread (mirroring separate concurrent requests),
    must all complete without error and leave the rider's cached position
    at exactly one of the submitted points — never a torn/mixed value.

    Uses a temp-file-backed SQLite database (a real connection per thread)
    rather than the in-memory StaticPool engine used elsewhere in this
    file — StaticPool hands every session the *same* raw DBAPI connection
    object, which genuinely isn't safe to operate on concurrently from
    multiple threads regardless of application logic, unlike a real
    production connection pool against Postgres."""
    db_path = Path(tmp_path) / "concurrency.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)

    with Session(engine) as seed:
        rider = _online_rider(seed, email="concurrent@example.com", phone="8000000001")
        rider_id = rider.id

    coordinates = [(Decimal(f"12.9{i}00"), Decimal(f"77.5{i}00")) for i in range(5)]
    errors: list[Exception] = []

    def _do_update(lat, lon):
        try:
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                update_rider_location(worker, worker_rider, lat, lon)
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=_do_update, args=(lat, lon)) for lat, lon in coordinates]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []

    with Session(engine) as verify:
        final_rider = verify.get(User, rider_id)
        final_point = (final_rider.current_latitude, final_rider.current_longitude)
        assert final_point in coordinates  # last-write-wins, not a corrupted mix

        history_count = verify.scalar(select(func.count()).select_from(RiderLocationPing).where(RiderLocationPing.rider_id == rider_id))
        assert 1 <= history_count <= len(coordinates)


def test_location_update_arriving_after_delivery_completes_does_not_broadcast(engine, monkeypatch):
    """A location update that lands just after the order reaches DELIVERED
    must still be accepted (the rider may still be online) but must not
    broadcast to an order that's already left the trackable window."""
    with Session(engine) as seed:
        rider = _online_rider(seed, email="post-delivery@example.com", phone="8000000002")
        order = _assigned_order(seed, rider)
        transition_order_status(seed, order, OrderStatus.PICKED_UP)
        transition_order_status(seed, order, OrderStatus.OUT_FOR_DELIVERY)
        transition_order_status(seed, order, OrderStatus.DELIVERED)
        rider_id = rider.id
        order_id = order.id

    broadcasts: list[tuple] = []
    monkeypatch.setattr(
        "app.services.rider_location.manager.broadcast",
        lambda oid, payload: broadcasts.append((oid, payload)),
    )

    with Session(engine) as worker:
        worker_rider = worker.get(User, rider_id)
        # Should not raise — the rider is still online independent of this order.
        update_rider_location(worker, worker_rider, Decimal("12.9800"), Decimal("77.6000"))

    assert all(oid != order_id for oid, _ in broadcasts)


def test_reassigned_rider_location_updates_no_longer_target_the_old_order(engine, monkeypatch):
    """Once an order is reassigned to a different rider, the outgoing
    rider's own subsequent location updates must not broadcast to that
    order anymore — the reassignment must take effect immediately, not
    only after the outgoing rider's connection happens to notice."""
    with Session(engine) as seed:
        rider_a = _online_rider(seed, email="rider-a@example.com", phone="8000000003")
        rider_b = _online_rider(seed, email="rider-b@example.com", phone="8000000004")
        order = _assigned_order(seed, rider_a)
        admin = User(name="Admin", email="admin-concurrency@example.com", password_hash="x", role=UserRole.ADMIN, phone="8000000005")
        seed.add(admin)
        seed.commit()

        admin_reassign_rider(seed, admin, order.id, rider_b.id, reason="rider A unreachable")

        rider_a_id = rider_a.id
        rider_b_id = rider_b.id
        order_id = order.id

    # This test is about broadcast *targeting*, not the Phase 35
    # has_listeners optimization (which would otherwise skip building a
    # snapshot at all here, since no real WS connection exists in this
    # service-layer test) — simulate an always-listening room so the
    # targeting behavior underneath is what's actually being exercised.
    monkeypatch.setattr("app.services.rider_location.manager.has_listeners", lambda order_id: True)
    broadcasts: list[tuple] = []
    monkeypatch.setattr(
        "app.services.rider_location.manager.broadcast",
        lambda oid, payload: broadcasts.append((oid, payload)),
    )

    with Session(engine) as worker:
        stale_rider = worker.get(User, rider_a_id)
        update_rider_location(worker, stale_rider, Decimal("12.9900"), Decimal("77.6100"))
    assert all(oid != order_id for oid, _ in broadcasts), "the outgoing rider must not still be able to broadcast to this order"

    broadcasts.clear()
    with Session(engine) as worker:
        new_rider = worker.get(User, rider_b_id)
        update_rider_location(worker, new_rider, Decimal("12.9901"), Decimal("77.6101"))
    assert any(oid == order_id for oid, _ in broadcasts), "the newly-assigned rider's position should broadcast to this order"


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload):
        if self.closed:
            raise RuntimeError("send on a closed socket")
        self.sent.append(payload)

    async def close(self, code=1000):
        self.closed = True


def test_manager_stops_broadcasting_once_a_room_is_closed():
    """Direct unit test of OrderTrackingConnectionManager (independent of
    the full WS stack) — after close_room(), the room is unregistered and
    a later broadcast() to the same order id is a silent no-op, never a
    send attempted against an already-closed socket."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        mgr = OrderTrackingConnectionManager()
        mgr.bind_loop(loop)
        order_id = uuid4()
        ws = _FakeWebSocket()

        asyncio.run_coroutine_threadsafe(mgr.connect(order_id, ws), loop).result(timeout=2)

        mgr.broadcast(order_id, {"n": 1})
        time.sleep(0.2)
        assert ws.sent == [{"n": 1}]

        mgr.close_room(order_id)
        time.sleep(0.2)
        assert ws.closed is True
        assert order_id not in mgr._connections

        mgr.broadcast(order_id, {"n": 2})
        time.sleep(0.2)
        assert ws.sent == [{"n": 1}]  # the stale room received nothing further
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
