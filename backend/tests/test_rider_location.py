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
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
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


def test_offline_rider_with_no_active_delivery_update_is_rejected():
    """Live Rider Tracking Phase 6 — an offline rider with no active
    delivery has nothing to report location for, and the endpoint now says
    so explicitly (403) rather than silently accepting and discarding the
    call, so the rider app has something concrete to react to."""
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
            assert response.status_code == 403

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


def test_rapid_successive_updates_at_essentially_the_same_point_are_throttled_in_the_history_table():
    """The cache (User.current_latitude/etc.) updates on every accepted
    call, but the durable history ledger must not grow one row per rapid
    update — only one row should exist after several calls made faster than
    MIN_LOCATION_PING_INTERVAL_SECONDS apart, *and* with no meaningful
    movement between them (Live Rider Tracking Phase 7's throttle is
    time-OR-distance — see the dedicated movement-triggers-storage test
    below for the other half of that rule)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="throttle-rider@example.com")
            token = create_access_token(rider.id)
            rider_id = rider.id

        with _client_with_db(engine) as client:
            for i in range(5):
                # The 6th decimal place is ~11cm of latitude — real GPS
                # jitter, not meaningful movement, well under the 15m
                # movement threshold.
                response = client.patch(
                    "/api/v1/rider/location",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"latitude": f"12.970000{i}", "longitude": "77.590000"},
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
                json={"latitude": "12.9700005", "longitude": "77.590000"},
            )
            assert float(latest.json()["latitude"]) == pytest.approx(12.9700005)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_significant_movement_triggers_storage_even_within_the_time_throttle_window():
    """Live Rider Tracking Phase 7 — the other half of the time-OR-distance
    rule: a rider covering real ground within the 10s window still gets a
    second history row, even though not enough time has passed."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="movement-throttle-rider@example.com")
            token = create_access_token(rider.id)
            rider_id = rider.id

        with _client_with_db(engine) as client:
            client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900"},
            )
            # ~1km away — well over the 15m movement threshold — sent
            # immediately after, inside the 10s time window.
            client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9800", "longitude": "77.5900"},
            )

        with Session(engine) as check:
            assert check.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider_id).count() == 2
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_an_implausible_gps_jump_with_poor_accuracy_is_rejected():
    """Live Rider Tracking Phase 8 — GPS Accuracy Filtering. Poor accuracy
    AND an implied speed far beyond any real delivery vehicle, together,
    is rejected outright."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="jump-rider@example.com")
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            first = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900", "accuracy": "10"},
            )
            assert first.status_code == 200

            # ~500km away, moments later, with terrible accuracy — an
            # implied speed no real vehicle reaches.
            jump = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "17.9700", "longitude": "77.5900", "accuracy": "500"},
            )
            assert jump.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_large_jump_with_good_accuracy_is_accepted_not_rejected():
    """Live Rider Tracking Phase 8's own instruction: "do not blindly
    reject legitimate GPS behavior... keep filtering conservative." Good
    accuracy alone is enough to accept a big movement — real GPS units do
    report large, genuine jumps (e.g. after a tunnel) with fine accuracy."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="good-accuracy-jump-rider@example.com")
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900", "accuracy": "5"},
            )
            jump = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "17.9700", "longitude": "77.5900", "accuracy": "5"},
            )
            assert jump.status_code == 200
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_an_implausible_timestamp_is_rejected():
    """Live Rider Tracking Phase 6/8 — a captured_at far in the past (a
    stuck/wrong device clock) or future is rejected outright."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="bad-timestamp-rider@example.com")
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            stale = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={
                    "latitude": "12.9700", "longitude": "77.5900",
                    "captured_at": (datetime.now(UTC) - timedelta(hours=5)).isoformat(),
                },
            )
            assert stale.status_code == 422

            future = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={
                    "latitude": "12.9700", "longitude": "77.5900",
                    "captured_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            assert future.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_plausible_timestamp_and_altitude_round_trip_and_get_stored():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="altitude-rider@example.com")
            token = create_access_token(rider.id)
            rider_id = rider.id

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={
                    "latitude": "12.9700", "longitude": "77.5900", "altitude": "820.5",
                    "captured_at": datetime.now(UTC).isoformat(),
                },
            )
            assert response.status_code == 200

        with Session(engine) as check:
            ping = check.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider_id).first()
            assert ping.altitude == Decimal("820.50")
            assert ping.captured_at is not None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_ping_while_on_an_active_delivery_is_tagged_with_its_order_and_assignment():
    """Live Rider Tracking Phase 3 — assignment_id/order_id let a history
    row be tied back to which specific delivery it belonged to."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="tagged-ping-rider@example.com")
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("100.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
                "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "560001",
            })
            order = create_order(seed, customer, address.id)
            for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
                transition_order_status(seed, order, target)
            assign_rider_to_order(seed, order, rider.id)
            assignment = DeliveryAssignment(order_id=order.id, rider_id=rider.id, status=AssignmentStatus.ACCEPTED)
            seed.add(assignment)
            seed.commit()
            token = create_access_token(rider.id)
            order_id, assignment_id, rider_id = order.id, assignment.id, rider.id

        with _client_with_db(engine) as client:
            response = client.patch(
                "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
                json={"latitude": "12.9700", "longitude": "77.5900"},
            )
            assert response.status_code == 200

        with Session(engine) as check:
            ping = (
                check.query(RiderLocationPing)
                .filter(RiderLocationPing.rider_id == rider_id)
                .order_by(RiderLocationPing.recorded_at.desc())
                .first()
            )
            assert ping.order_id == order_id
            assert ping.assignment_id == assignment_id
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


def test_purge_rider_location_history_deletes_only_rows_past_the_retention_window(db):
    """Live Rider Tracking Phase 29 — Location History Policy."""
    from app.services.rider_location import purge_rider_location_history

    rider = _rider(db)
    old_ping = RiderLocationPing(
        rider_id=rider.id, latitude=Decimal("12.9700"), longitude=Decimal("77.5900"),
        recorded_at=datetime.now(UTC) - timedelta(days=45),
    )
    recent_ping = RiderLocationPing(
        rider_id=rider.id, latitude=Decimal("12.9800"), longitude=Decimal("77.6000"),
        recorded_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add_all([old_ping, recent_ping])
    db.commit()

    deleted = purge_rider_location_history(db, older_than_days=30)

    assert deleted == 1
    remaining = db.query(RiderLocationPing).filter(RiderLocationPing.rider_id == rider.id).all()
    assert len(remaining) == 1
    assert remaining[0].id == recent_ping.id


def test_rider_location_update_ignores_a_client_supplied_rider_id(db):
    """Live Rider Tracking Phase 30 — "never trust IDs supplied by
    clients." RiderLocationUpdate has no rider_id field at all, so a
    client attempting to smuggle one in has it silently dropped before
    update_rider_location ever runs — rider A can never move rider B."""
    rider_a = _online_rider(db, email="idor-rider-a2@example.com")
    rider_b = User(name="Rider B", email="idor-rider-b2@example.com", password_hash="x", role=UserRole.RIDER, phone="8888880002")
    db.add(rider_b)
    db.commit()
    token_a = create_access_token(rider_a.id)
    rider_a_id, rider_b_id = rider_a.id, rider_b.id

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/rider/location",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"latitude": "12.9700", "longitude": "77.5900", "rider_id": str(rider_b_id)},
            )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    db.refresh(rider_a)
    db.refresh(rider_b)
    assert rider_a.current_latitude == Decimal("12.9700000")
    assert rider_b.current_latitude is None


def test_rider_location_endpoint_is_rate_limited_per_rider():
    """Live Rider Tracking Phase 40 — Final Security Audit. This was the
    one tracking-surface endpoint with no rate limit at all before this
    phase."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            rider = _online_rider(seed, email="rate-limited-rider@example.com")
            token = create_access_token(rider.id)

        with _client_with_db(engine) as client:
            headers = {"Authorization": f"Bearer {token}"}
            for _ in range(30):
                response = client.patch(
                    "/api/v1/rider/location", headers=headers, json={"latitude": "12.9700", "longitude": "77.5900"},
                )
                assert response.status_code == 200

            response = client.patch(
                "/api/v1/rider/location", headers=headers, json={"latitude": "12.9700", "longitude": "77.5900"},
            )
            assert response.status_code == 429
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
