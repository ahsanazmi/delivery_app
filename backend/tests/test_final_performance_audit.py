"""Live Rider Tracking Phase 41 — Final Performance Audit.

Actually measures (not just reasons about) the dimensions this phase
names, wherever the dimension is something a test can genuinely time or
count: location update latency, broadcast latency (folded into "customer
marker update latency" — from this backend's perspective they're the same
in-process hop), database load (real query count, not an estimate), and
route API usage. Each measurement doubles as a regression guard — a
future change that silently makes any of these worse fails the test, not
just a one-time audit note.

WebSocket reconnect time and mobile battery impact are client-side,
design-time parameters with no server code to time — reported as
configured values (see the completion report / docs), not measured here.
"""

import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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


def _online_rider(db, *, email="rider@example.com", phone="8700000001"):
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


def test_location_update_latency_is_small_with_no_listener(engine):
    """"Location update latency" — the write path alone (validate,
    upsert the cache, throttled history write), with nobody connected to
    also pay for a broadcast."""
    with Session(engine) as seed:
        rider = _online_rider(seed)
        rider_id = rider.id

    with Session(engine) as worker:
        worker_rider = worker.get(User, rider_id)
        started = time.perf_counter()
        update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))
        elapsed_ms = (time.perf_counter() - started) * 1000

    # Generous bound for CI stability (SQLite in-memory; a real Postgres
    # single-row upsert is comparable or faster) — this is a regression
    # guard, not a tight production SLA.
    assert elapsed_ms < 200, f"location update took {elapsed_ms:.1f}ms, expected well under 200ms"


def test_location_update_issues_a_small_bounded_number_of_database_queries(engine):
    """"Database load" — a real, counted number, not an estimate. Counts
    every SQL statement SQLAlchemy actually sends for one accepted
    location update with no listener (the common case — most GPS pings
    happen while a customer isn't actively watching the live map)."""
    with Session(engine) as seed:
        rider = _online_rider(seed, email="dbload@example.com", phone="8700000002")
        rider_id = rider.id

    with Session(engine) as worker:
        worker_rider = worker.get(User, rider_id)
        statements: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(worker.get_bind(), "before_cursor_execute", _count)
        try:
            update_rider_location(worker, worker_rider, Decimal("12.9701"), Decimal("77.5901"))
        finally:
            event.remove(worker.get_bind(), "before_cursor_execute", _count)

    # Measured, then given headroom — not guessed. The actual count at
    # time of writing: a handful of reads (rider row, active-order lookup,
    # delivery-partner lookup, last-ping lookup, active-orders-for-broadcast
    # lookup) plus the UPDATE/INSERT/COMMIT writes. Asserting a ceiling
    # catches an accidental N+1 introduced later, without pinning to a
    # brittle exact number.
    assert len(statements) <= 12, f"expected a small, bounded query count; got {len(statements)}: {statements}"


def test_broadcast_and_customer_marker_update_latency_end_to_end(engine):
    """"Broadcast latency" and "customer marker update latency" folded
    into one measurement, since in this architecture they're the same
    in-process hop: time from calling update_rider_location (with a real
    connected customer) to that customer's WebSocket actually receiving
    the new position."""
    with Session(engine) as seed:
        rider = _online_rider(seed, email="latency-rider@example.com", phone="8700000003")
        customer = User(name="Cust", email="latency-customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
            transition_order_status(seed, order, target)
        assign_rider_to_order(seed, order, rider.id)
        rider_id, order_id = rider.id, order.id
        token = create_access_token(customer.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            started = time.perf_counter()
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                update_rider_location(worker, worker_rider, Decimal("12.9750"), Decimal("77.5950"))
            update = ws.receive_json()
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert update["rider_location"] is not None
    # Generous bound: this is an in-process asyncio hop (no network round
    # trip between the write and the push — see app/ws/manager.py), so a
    # real production figure is single-digit milliseconds; this test's
    # bound exists to catch a genuine regression (e.g. an accidental
    # synchronous sleep or a network call introduced on this path), not
    # to assert a tight SLA against test-harness scheduling noise.
    assert elapsed_ms < 1000, f"end-to-end broadcast took {elapsed_ms:.1f}ms, expected well under 1000ms"


def test_route_api_usage_is_bounded_across_several_rapid_updates(engine, monkeypatch):
    """"Route API usage" — several location updates in a tight loop, all
    within the Phase 24 refresh gate's time/distance window, must call
    the routing provider at most once, not once per update."""
    from app.schemas.location import RouteResult

    with Session(engine) as seed:
        rider = _online_rider(seed, email="route-usage-rider@example.com", phone="8700000004")
        customer = User(name="Cust", email="route-usage-customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        address_id = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
            "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            "latitude": Decimal("12.9800"), "longitude": Decimal("77.6000"),
        }).id
        product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
        seed.add(product)
        seed.commit()
        cart = create_cart_for_user(seed, customer.id)
        add_item(seed, cart, product.id, 1)
        order = create_order(seed, customer, address_id)
        for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
            transition_order_status(seed, order, target)
        assign_rider_to_order(seed, order, rider.id)
        rider_id, order_id = rider.id, order.id
        token = create_access_token(customer.id)

    call_count = 0

    def _counted_route(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return RouteResult(distance_km=1.0, duration_minutes=10.0)

    monkeypatch.setattr("app.services.location_service.route", _counted_route)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot
            for _ in range(5):
                with Session(engine) as worker:
                    worker_rider = worker.get(User, rider_id)
                    # Deliberately tiny movement each time — well inside
                    # the refresh gate's 300m/60s threshold.
                    update_rider_location(worker, worker_rider, Decimal("12.97001"), Decimal("77.59001"))
                ws.receive_json()

    assert call_count == 1, f"expected exactly one route computation across 5 tightly-clustered updates, got {call_count}"
