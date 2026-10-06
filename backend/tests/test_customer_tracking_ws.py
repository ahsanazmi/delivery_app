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
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.rider_location import update_rider_location


@pytest.fixture()
def ws_app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield engine
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _customer(session, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    session.add(user)
    session.commit()
    return user


def _restaurant(session):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    session.add(owner)
    session.commit()
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
    session.add(restaurant)
    session.commit()
    return restaurant


def _place_order(session, customer, restaurant):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    session.add(product)
    session.commit()
    cart = create_cart_for_user(session, customer.id)
    add_item(session, cart, product.id, 1)
    address = create_address(session, customer.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })
    return create_order(session, customer, address.id)


def test_ws_rejects_connection_without_token(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}"):
                pass


def test_ws_rejects_deactivated_user(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        token = create_access_token(customer.id)
        customer.is_active = False
        seed.commit()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}"):
                pass


def test_ws_rejects_invalid_token(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token=garbage"):
                pass


def test_ws_rejects_a_genuinely_expired_jwt(ws_app):
    """Live Rider Tracking Phase 30 — distinct from the malformed-token
    case above: a well-formed, correctly-signed token that has simply
    expired must be rejected too, not just garbage input."""
    import jwt as pyjwt

    from app.core.config import settings

    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        customer_id = customer.id

    from datetime import UTC, datetime, timedelta

    expired_token = pyjwt.encode(
        {
            "sub": str(customer_id), "type": "access", "jti": "expired-test",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM,
    )

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={expired_token}"):
                pass


def test_ws_rejects_order_owned_by_another_customer(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        other = _customer(seed, email="other@example.com")
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        other_token = create_access_token(other.id)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={other_token}"):
                pass


def test_ws_sends_initial_snapshot_on_connect(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        token = create_access_token(customer.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            snapshot = ws.receive_json()
            assert snapshot["order_id"] == str(order_id)
            assert snapshot["order_status"] == "placed"
            assert snapshot["rider_location"] is None


def test_ws_receives_broadcast_on_status_change(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        token = create_access_token(customer.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            with Session(engine) as worker:
                order = worker.get(type(order), order_id) or worker.query(type(order)).filter_by(id=order_id).first()
                transition_order_status(worker, order, OrderStatus.CONFIRMED)

            update = ws.receive_json()
            assert update["order_status"] == "confirmed"
            assert len(update["status_history"]) == 2


def test_ws_connection_is_closed_by_the_server_once_the_order_reaches_a_terminal_status(ws_app):
    """Live Rider Tracking Phase 28/31 — a stale connection left open
    after DELIVERED/CANCELLED/REJECTED must not stay registered waiting
    for a broadcast that will now never come; the server closes it."""
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        token = create_access_token(customer.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            with Session(engine) as worker:
                order = worker.query(type(order)).filter_by(id=order_id).first()
                transition_order_status(worker, order, OrderStatus.CANCELLED, "customer cancelled")

            terminal_update = ws.receive_json()
            assert terminal_update["order_status"] == "cancelled"

            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_ws_broadcasts_rider_location_only_once_visible(ws_app):
    engine = ws_app
    with Session(engine) as seed:
        customer = _customer(seed)
        restaurant = _restaurant(seed)
        order = _place_order(seed, customer, restaurant)
        order_id = order.id
        token = create_access_token(customer.id)
        rider = User(name="Rider Bob", email="rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8888888888")
        seed.add(rider)
        seed.commit()
        rider_id = rider.id

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            ws.receive_json()  # initial snapshot

            with Session(engine) as worker:
                from app.models.order import Order as OrderModel

                order = worker.get(OrderModel, order_id)
                rider = worker.get(User, rider_id)
                transition_order_status(worker, order, OrderStatus.CONFIRMED)
            confirmed = ws.receive_json()
            assert confirmed["rider_location"] is None

            with Session(engine) as worker:
                from app.models.order import Order as OrderModel

                order = worker.get(OrderModel, order_id)
                rider = worker.get(User, rider_id)
                assign_rider_to_order(worker, order, rider.id)
            assigned = ws.receive_json()
            assert assigned["assignment_status"] == "assigned"
            assert assigned["rider_location"] is None  # rider hasn't reported a position yet

            with Session(engine) as worker:
                rider = worker.get(User, rider_id)
                update_rider_location(worker, rider, Decimal("12.9700"), Decimal("77.5900"))
            located = ws.receive_json()
            assert located["rider_location"] is not None
            assert located["rider_location"]["latitude"] == pytest.approx(12.97)


def test_ws_broadcast_isolation_between_two_different_orders(ws_app):
    """Live Rider Tracking Phase 36 — Automated Testing: "broadcast
    isolation." Two customers, each watching a different order at once —
    a change to order A must never be visible on customer B's socket
    (order_id mismatch would prove a cross-room leak in
    OrderTrackingConnectionManager, which keys its connections dict by
    order_id — this is the end-to-end proof that keying actually holds)."""
    engine = ws_app
    with Session(engine) as seed:
        customer_a = _customer(seed, email="customer-a@example.com")
        customer_b = _customer(seed, email="customer-b@example.com")
        restaurant = _restaurant(seed)
        order_a = _place_order(seed, customer_a, restaurant)
        order_b = _place_order(seed, customer_b, restaurant)
        order_a_id, order_b_id = order_a.id, order_b.id
        token_a = create_access_token(customer_a.id)
        token_b = create_access_token(customer_b.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_a_id}?token={token_a}") as ws_a:
            with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_b_id}?token={token_b}") as ws_b:
                ws_a.receive_json()  # initial snapshot, order A
                ws_b.receive_json()  # initial snapshot, order B

                with Session(engine) as worker:
                    order = worker.query(type(order_a)).filter_by(id=order_a_id).first()
                    transition_order_status(worker, order, OrderStatus.CONFIRMED)
                update_a = ws_a.receive_json()
                assert update_a["order_id"] == str(order_a_id)
                assert update_a["order_status"] == "confirmed"

                with Session(engine) as worker:
                    order = worker.query(type(order_b)).filter_by(id=order_b_id).first()
                    transition_order_status(worker, order, OrderStatus.CONFIRMED)
                # If order A's change had leaked into B's room, this would
                # be B's *second* queued message and/or carry order A's id.
                update_b = ws_b.receive_json()
                assert update_b["order_id"] == str(order_b_id)
                assert update_b["order_status"] == "confirmed"
