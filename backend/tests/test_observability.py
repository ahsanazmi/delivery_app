"""Live Rider Tracking Phase 39 — Observability.

Verifies each of the 11 named structured events actually gets logged at
the point it claims to, and — just as important — that nothing sensitive
(the WebSocket auth token, in particular) ever ends up in a log line.
"""

import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.schemas.location import RouteResult
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


def _online_rider(db, *, email="rider@example.com", phone="8600000001"):
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
        "latitude": Decimal("12.9800"), "longitude": Decimal("77.6000"),
    })
    return create_order(db, customer, address.id)


def _events(caplog):
    return [r.message.split(" ", 1)[0] for r in caplog.records if r.message.startswith("event=")]


def test_location_received_and_tracking_started_are_logged_for_the_first_ping_on_an_order(engine, caplog):
    with Session(engine) as seed:
        rider = _online_rider(seed)
        customer = User(name="Cust", email="c1@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
            transition_order_status(seed, order, target)
        assign_rider_to_order(seed, order, rider.id)
        rider_id = rider.id

    with caplog.at_level(logging.INFO):
        with Session(engine) as worker:
            worker_rider = worker.get(User, rider_id)
            update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))

    events = _events(caplog)
    assert "event=tracking_started" in events
    assert "event=location_received" in events


def test_location_rejected_is_logged_for_an_ineligible_rider(engine, caplog):
    with Session(engine) as seed:
        rider = User(name="Rider", email="ineligible@example.com", password_hash="x", role=UserRole.RIDER, phone="8600000002")
        seed.add(rider)
        seed.commit()
        rider_id = rider.id

    with caplog.at_level(logging.INFO):
        with Session(engine) as worker:
            worker_rider = worker.get(User, rider_id)
            with pytest.raises(Exception):
                update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))

    assert "event=location_rejected" in _events(caplog)


def test_location_filtered_is_logged_when_the_history_write_is_throttled(engine, caplog):
    with Session(engine) as seed:
        rider = _online_rider(seed, email="throttle@example.com", phone="8600000003")
        rider_id = rider.id

    with Session(engine) as worker:
        worker_rider = worker.get(User, rider_id)
        update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))

    with caplog.at_level(logging.INFO):
        with Session(engine) as worker:
            worker_rider = worker.get(User, rider_id)
            # Same rider, immediately again, barely any movement — inside
            # both the time and distance throttle window.
            update_rider_location(worker, worker_rider, Decimal("12.9700001"), Decimal("77.5900001"))

    assert "event=location_filtered" in _events(caplog)


def test_websocket_and_subscription_events_are_logged_on_connect_and_disconnect(engine, caplog):
    with Session(engine) as seed:
        customer = User(name="Cust", email="ws-obs@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id, customer_id = order.id, customer.id
        token = create_access_token(customer_id)

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
                ws.receive_json()

    events = _events(caplog)
    assert "event=websocket_connected" in events
    assert "event=subscription_created" in events
    assert "event=websocket_disconnected" in events


def test_subscription_rejected_is_logged_and_never_includes_the_token(engine, caplog):
    with Session(engine) as seed:
        customer = User(name="Cust", email="ws-obs-2@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id

    secret_looking_token = "not-a-real-but-secret-shaped-token-value-should-never-appear-in-logs"

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={secret_looking_token}"):
                    pass

    assert "event=subscription_rejected" in _events(caplog)
    for record in caplog.records:
        assert secret_looking_token not in record.message


def test_tracking_stopped_is_logged_once_an_order_reaches_a_terminal_status(engine, caplog):
    with Session(engine) as seed:
        customer = User(name="Cust", email="c2@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id

    with caplog.at_level(logging.INFO):
        with Session(engine) as worker:
            order = worker.get(type(order), order_id)
            transition_order_status(worker, order, OrderStatus.CANCELLED, "customer cancelled")

    assert "event=tracking_stopped" in _events(caplog)


def test_eta_refresh_is_logged_only_on_a_fresh_live_computation(engine, caplog, monkeypatch):
    with Session(engine) as seed:
        rider = _online_rider(seed, email="eta-obs@example.com", phone="8600000004")
        customer = User(name="Cust", email="c3@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
            transition_order_status(seed, order, target)
        assign_rider_to_order(seed, order, rider.id)
        rider_id, order_id = rider.id, order.id
        token = create_access_token(customer.id)

    monkeypatch.setattr(
        "app.services.location_service.route",
        lambda *a, **k: RouteResult(distance_km=1.0, duration_minutes=12.0),
    )

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            with caplog.at_level(logging.INFO):
                with Session(engine) as worker:
                    worker_rider = worker.get(User, rider_id)
                    update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))
                ws.receive_json()

    assert "event=eta_refresh" in _events(caplog)


def test_tracking_error_is_logged_when_the_broadcast_layer_fails(engine, caplog, monkeypatch):
    """Live Rider Tracking Phase 32's failure-isolation guard — a broadcast
    failure must be observable (this event), even though it's deliberately
    never allowed to abort the caller."""
    with Session(engine) as seed:
        rider = _online_rider(seed, email="error-obs@example.com", phone="8600000005")
        customer = User(name="Cust", email="c4@example.com", password_hash="x", role=UserRole.CUSTOMER)
        seed.add(customer)
        seed.commit()
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
            transition_order_status(seed, order, target)
        assign_rider_to_order(seed, order, rider.id)
        rider_id, order_id = rider.id, order.id
        token = create_access_token(customer.id)

    monkeypatch.setattr(
        "app.services.rider_location.manager.broadcast",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated broadcast failure")),
    )

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            with caplog.at_level(logging.INFO):
                with Session(engine) as worker:
                    worker_rider = worker.get(User, rider_id)
                    update_rider_location(worker, worker_rider, Decimal("12.9700"), Decimal("77.5900"))

    assert "event=tracking_error" in _events(caplog)
