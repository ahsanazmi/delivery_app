from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import OrderStatus
from app.models.rider_location import RiderLocationPing
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _rider(db, email="rider@example.com"):
    rider = User(name="Rider Bob", email=email, password_hash="x", role=UserRole.RIDER, phone="8888888888")
    db.add(rider)
    db.commit()
    return rider


def _online_rider(db, email="online-rider@example.com"):
    rider = _rider(db, email)
    partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
    db.add(partner)
    db.commit()
    return rider


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


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


def _client_with_db(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_rider_location_endpoint_requires_rider_role():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.97", "longitude": "77.59"},
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_online_rider_location_update_is_stored_and_returned():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed)
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900", "accuracy": "8.5", "heading": "180.0", "speed": "4.2"},
            )
            assert response.status_code == 200
            body = response.json()
            assert float(body["latitude"]) == pytest.approx(12.97)
            assert float(body["longitude"]) == pytest.approx(77.59)
            assert float(body["accuracy"]) == pytest.approx(8.5)
            assert float(body["heading"]) == pytest.approx(180.0)
            assert float(body["speed"]) == pytest.approx(4.2)
            assert body["updated_at"] is not None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_rider_location_rejects_out_of_range_coordinates():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed)
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "999", "longitude": "77.59"},
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_offline_rider_with_no_active_delivery_update_is_a_no_op():
    """The Phase 22 rule enforced server-side: an offline rider with no
    active delivery has nothing to report location for. Not an error — the
    request still succeeds, but the position is neither stored nor
    broadcast, and the echoed response reflects that nothing changed."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _rider(seed)  # no DeliveryPartner row at all -> not online
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["latitude"] is None
            assert body["longitude"] is None
            assert body["updated_at"] is None

        with Session(engine) as check:
            assert check.query(RiderLocationPing).count() == 0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_offline_rider_with_active_delivery_can_still_report_location():
    """Eligibility is "ONLINE *or* has an active delivery" — a rider who has
    gone offline mid-delivery (edge case, but reachable) should still be
    trackable for that one order in progress."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _rider(seed, email="active-delivery-rider@example.com")
            restaurant = _restaurant(seed)
            customer = _customer(seed, email="cust-active@example.com")
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
                "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            })
            order = create_order(seed, customer, address.id)
            transition_order_status(seed, order, OrderStatus.CONFIRMED)
            transition_order_status(seed, order, OrderStatus.PREPARING)
            transition_order_status(seed, order, OrderStatus.READY_FOR_PICKUP)
            assign_rider_to_order(seed, order, rider.id)
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900"},
            )
            assert response.status_code == 200
            body = response.json()
            assert float(body["latitude"]) == pytest.approx(12.97)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_rapid_successive_updates_are_throttled_in_the_history_table():
    """The cache (User.current_latitude/etc.) updates on every accepted
    call, but the durable history ledger must not grow one row per rapid
    update — only one row should exist after several calls made faster than
    MIN_LOCATION_PING_INTERVAL_SECONDS apart."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="throttle-rider@example.com")
            token = create_access_token(rider.id)
            rider_id = rider.id

        with _client_with_db(engine) as client:
            for i in range(5):
                response = client.patch(
                    "/api/v1/rider/location",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"latitude": f"12.97{i}", "longitude": "77.5900"},
                )
                assert response.status_code == 200

        with Session(engine) as check:
            pings = check.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider_id).all()
            assert len(pings) == 1

        # The cache still reflects the LAST call's position even though only
        # the first was persisted to history.
        with _client_with_db(engine) as client:
            latest = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "13.0000", "longitude": "77.5900"},
            )
            assert float(latest.json()["latitude"]) == pytest.approx(13.0)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_ping_older_than_the_throttle_window_is_stored():
    """A ping arriving after the throttle window has elapsed since the last
    stored one must still be recorded — this isn't a blanket rate limit,
    just a floor on how close together two rows can be."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="stale-throttle-rider@example.com")
            token = create_access_token(rider.id)
            rider_id = rider.id

        with _client_with_db(engine) as client:
            client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900"},
            )

        # Backdate the one stored ping well past the throttle window.
        with Session(engine) as backdate:
            ping = backdate.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider_id).first()
            ping.recorded_at = datetime.now(UTC) - timedelta(minutes=5)
            backdate.commit()

        with _client_with_db(engine) as client:
            client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "13.0000", "longitude": "77.5900"},
            )

        with Session(engine) as check:
            assert check.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider_id).count() == 2
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
