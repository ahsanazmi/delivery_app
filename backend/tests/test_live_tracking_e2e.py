"""Live Rider Tracking Phase 37 — End-to-End Live Tracking Test.

Runs the master command's own full real-world simulation as one
continuous flow, verifying every named transition along the way:

placed -> confirmed -> preparing -> ready_for_pickup -> rider assigned
(accepts) -> rider starts tracking (GPS updates, backend validates,
WebSocket broadcasts, customer sees rider movement, ETA updates) ->
picked up -> out for delivery -> rider reaches customer -> delivered ->
tracking stops (the WS room closes).

The customer side is driven through the *real* WebSocket endpoint (not
just the REST snapshot), since "customer sees rider movement" and
"WebSocket broadcasts" are literally what this phase asks to verify.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.rider_earning import RiderEarning
from app.schemas.location import RouteResult
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, collect_cod_payment, complete_delivery, pickup_delivery, start_delivery
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


# Restaurant near (12.9700, 77.5900); delivery address ~2.5km away.
RESTAURANT_LAT, RESTAURANT_LNG = Decimal("12.9700"), Decimal("77.5900")
DELIVERY_LAT, DELIVERY_LNG = Decimal("12.9900"), Decimal("77.6100")


def test_full_live_tracking_lifecycle_every_transition(engine, monkeypatch):
    with Session(engine) as seed:
        customer = User(name="Cust", email="e2e-customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        owner = User(name="Owner", email="e2e-owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
        rider = User(name="Rider", email="e2e-rider@example.com", password_hash="x", role=UserRole.RIDER, phone="8400000001")
        seed.add_all([customer, owner, rider])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=RESTAURANT_LAT, longitude=RESTAURANT_LNG,
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("40.00"), delivery_time_minutes=30,
        )
        seed.add(restaurant)
        seed.commit()
        partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
        seed.add(partner)

        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("150.00"))
        seed.add(product)
        seed.commit()
        cart = create_cart_for_user(seed, customer.id)
        add_item(seed, cart, product.id, 1)
        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
            "address_line": "1 Lake Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            "latitude": DELIVERY_LAT, "longitude": DELIVERY_LNG,
        })

        # Step 1: customer places order.
        order = create_order(seed, customer, address.id, payment_method="cod")
        assert order.status == OrderStatus.PLACED
        order_id, customer_id, rider_id = order.id, customer.id, rider.id

    token = create_access_token(customer_id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/{order_id}?token={token}") as ws:
            snapshot = ws.receive_json()
            assert snapshot["order_status"] == "placed"
            assert snapshot["rider_location"] is None

            # Step 2: restaurant confirms.
            with Session(engine) as worker:
                order = worker.get(type(order), order_id)
                transition_order_status(worker, order, OrderStatus.CONFIRMED)
            assert ws.receive_json()["order_status"] == "confirmed"

            # Step 3: restaurant prepares.
            with Session(engine) as worker:
                order = worker.get(type(order), order_id)
                transition_order_status(worker, order, OrderStatus.PREPARING)
            assert ws.receive_json()["order_status"] == "preparing"

            # Step 4: order ready.
            with Session(engine) as worker:
                order = worker.get(type(order), order_id)
                transition_order_status(worker, order, OrderStatus.READY_FOR_PICKUP)
            assert ws.receive_json()["order_status"] == "ready_for_pickup"

            # Step 5: rider assigned + accepts (this codebase's real accept
            # flow does both atomically — see accept_delivery's own docstring).
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                accept_delivery(worker, worker_rider, order_id)
            assigned = ws.receive_json()
            assert assigned["order_status"] == "rider_assigned"
            assert assigned["assignment_status"] == "assigned"
            assert assigned["rider"]["id"] == str(rider_id)
            assert assigned["rider_location"] is None  # not yet reported

            # Step 6: rider starts tracking — first GPS report, at the
            # restaurant ("rider reaches restaurant"). Backend validates
            # (200, accepted) and broadcasts it live.
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                update_rider_location(worker, worker_rider, RESTAURANT_LAT, RESTAURANT_LNG)
            at_restaurant = ws.receive_json()
            assert at_restaurant["rider_location"] is not None
            assert at_restaurant["rider_location"]["state"] == "live"
            assert float(at_restaurant["rider_location"]["latitude"]) == pytest.approx(float(RESTAURANT_LAT))

            # Step 7: rider picks up.
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                pickup_delivery(worker, worker_rider, order_id)
            assert ws.receive_json()["order_status"] == "picked_up"

            # Step 8: rider starts travelling toward the customer.
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                start_delivery(worker, worker_rider, order_id)
            assert ws.receive_json()["order_status"] == "out_for_delivery"

            # Step 9: cash collected before completion is allowed (this is
            # a COD order — the real precondition complete_delivery enforces).
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                collect_cod_payment(worker, worker_rider, order_id)

            # Step 10/11: GPS updates while travelling, each far enough
            # apart to force a fresh live-ETA computation — "backend
            # validates", "WebSocket broadcasts", "customer sees rider
            # movement", and "ETA updates" all verified on each hop.
            route_durations = iter([18.0, 9.0, 3.0])
            monkeypatch.setattr(
                "app.services.location_service.route",
                lambda *a, **k: RouteResult(distance_km=1.0, duration_minutes=next(route_durations)),
            )
            waypoints = [
                (Decimal("12.9750"), Decimal("77.5950")),
                (Decimal("12.9820"), Decimal("77.6020")),
                (Decimal("12.9895"), Decimal("77.6095")),  # "rider reaches customer"
            ]
            seen_etas: list[str] = []
            for latitude, longitude in waypoints:
                with Session(engine) as worker:
                    worker_rider = worker.get(User, rider_id)
                    update_rider_location(worker, worker_rider, latitude, longitude)
                update = ws.receive_json()
                assert update["rider_location"]["state"] == "live"
                assert float(update["rider_location"]["latitude"]) == pytest.approx(float(latitude))
                assert update["eta_source"] == "live"
                seen_etas.append(update["estimated_delivery_at"])
            assert len(set(seen_etas)) == len(seen_etas), "ETA must actually move as the rider gets closer, not stay frozen"

            # The final waypoint was within the Phase 34 proximity radius —
            # confirms "rider reaches customer" is independently observable.
            with Session(engine) as check:
                approaching = check.scalar(
                    select(Notification).where(Notification.order_id == order_id, Notification.type == NotificationType.RIDER_APPROACHING)
                )
                assert approaching is not None

            # Step 12: delivery completed.
            with Session(engine) as worker:
                worker_rider = worker.get(User, rider_id)
                complete_delivery(worker, worker_rider, order_id)
            delivered = ws.receive_json()
            assert delivered["order_status"] == "delivered"

            # Step 13: tracking stops — the server proactively closes the
            # room once the order is terminal (Phase 28); no further
            # message will ever arrive on this connection.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    # Cross-cutting correctness, not just the tracking surface: the order
    # itself, COD settlement, and the rider's earning all landed correctly
    # too — a live-tracking bug along the way must never have silently
    # corrupted any of this, per the master command's own standing rule.
    with Session(engine) as final:
        final_order = final.get(type(order), order_id)
        assert final_order.status == OrderStatus.DELIVERED
        assert final_order.is_paid is True
        earning = final.scalar(select(RiderEarning).where(RiderEarning.order_id == order_id))
        assert earning is not None
