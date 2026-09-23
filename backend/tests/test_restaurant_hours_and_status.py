"""Restaurant Owner Portal — Phase 4: open/close status and operating hours."""

from datetime import UTC, datetime, time
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
from app.models.restaurant_hours import RestaurantOperatingHours
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.checkout import validate_checkout
from app.services.restaurant_hours import compute_is_accepting_orders, is_within_operating_hours


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com", phone="9000000001"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House", is_open=True):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"), is_open=is_open,
    )
    db.add(restaurant)
    db.commit()
    return restaurant


# ---------------------------------------------------------------------------
# Pure hours-computation logic
# ---------------------------------------------------------------------------


def test_no_hours_configured_means_manual_toggle_alone_decides(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    assert compute_is_accepting_orders(restaurant, []) is True

    restaurant.is_open = False
    assert compute_is_accepting_orders(restaurant, []) is False


def test_within_configured_hours_is_accepting(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)  # 2026-09-07 is a Monday
    assert monday_noon.weekday() == 0
    hours = [RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=0, open_time=time(10, 0), close_time=time(22, 0))]

    assert is_within_operating_hours(hours, monday_noon) is True
    assert compute_is_accepting_orders(restaurant, hours, monday_noon) is True


def test_outside_configured_hours_is_not_accepting_even_if_toggle_says_open(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)  # manually "open"
    monday_3am = datetime(2026, 9, 7, 3, 0, tzinfo=UTC)
    hours = [RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=0, open_time=time(10, 0), close_time=time(22, 0))]

    assert is_within_operating_hours(hours, monday_3am) is False
    assert compute_is_accepting_orders(restaurant, hours, monday_3am) is False


def test_day_marked_closed_overrides_open_time(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    hours = [RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=0, is_closed=True)]

    assert is_within_operating_hours(hours, monday_noon) is False


def test_manual_toggle_off_wins_even_within_hours(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=False)  # manually closed
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    hours = [RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=0, open_time=time(10, 0), close_time=time(22, 0))]

    assert compute_is_accepting_orders(restaurant, hours, monday_noon) is False


def test_missing_day_in_configured_week_means_closed_that_day(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    # Only Tuesday configured — Monday has no row at all.
    hours = [RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=1, open_time=time(10, 0), close_time=time(22, 0))]

    assert is_within_operating_hours(hours, monday_noon) is False


# ---------------------------------------------------------------------------
# Checkout enforcement — the real gate
# ---------------------------------------------------------------------------


def _place_ready_cart(db, restaurant):
    customer = User(name="Customer", email="cust@example.com", phone="9111111111", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return customer, address


def test_checkout_blocked_outside_hours_even_when_manually_open(db, monkeypatch):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    customer, address = _place_ready_cart(db, restaurant)

    # Configure hours so "now" (whatever it really is) falls outside them by
    # closing every day — deterministic regardless of when the test runs.
    hours = [
        RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=day, is_closed=True)
        for day in range(7)
    ]
    db.add_all(hours)
    db.commit()

    result = validate_checkout(db, customer, address.id)
    assert result["valid"] is False
    assert "currently closed" in " ".join(result["issues"])


def test_checkout_allowed_when_no_hours_configured_and_manually_open(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner, is_open=True)
    customer, address = _place_ready_cart(db, restaurant)

    result = validate_checkout(db, customer, address.id)
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def _http_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def _teardown(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_status_endpoint_reflects_manual_toggle_and_hours():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner, is_open=True)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get("/api/v1/restaurant/status", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["is_open"] is True
            assert body["hours_configured"] is False
            assert body["is_accepting_orders"] is True  # no hours configured yet
    finally:
        _teardown(engine)


def test_patch_status_toggles_open_closed():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner, is_open=True)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = client.patch("/api/v1/restaurant/status", headers=headers, json={"is_open": False})
            assert response.status_code == 200
            body = response.json()
            assert body["is_open"] is False
            assert body["is_accepting_orders"] is False
    finally:
        _teardown(engine)


def test_put_hours_full_week_round_trip():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        week = [
            {"day_of_week": d, "is_closed": False, "open_time": "10:00:00", "close_time": "22:00:00"}
            for d in range(6)
        ] + [{"day_of_week": 6, "is_closed": False, "open_time": "11:00:00", "close_time": "21:00:00"}]

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            put_response = client.put("/api/v1/restaurant/hours", headers=headers, json={"hours": week})
            assert put_response.status_code == 200
            assert len(put_response.json()["hours"]) == 7

            get_response = client.get("/api/v1/restaurant/hours", headers=headers)
            assert get_response.status_code == 200
            hours = get_response.json()["hours"]
            sunday = next(h for h in hours if h["day_of_week"] == 6)
            assert sunday["open_time"] == "11:00:00"
            assert sunday["close_time"] == "21:00:00"
            assert sunday["day_name"] == "Sunday"
    finally:
        _teardown(engine)


def test_put_hours_rejects_incomplete_week():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = client.put(
                "/api/v1/restaurant/hours",
                headers=headers,
                json={"hours": [{"day_of_week": 0, "open_time": "10:00:00", "close_time": "22:00:00"}]},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_put_hours_rejects_open_after_close():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        week = [{"day_of_week": d, "open_time": "22:00:00", "close_time": "10:00:00"} for d in range(7)]

        with TestClient(app) as client:
            response = client.put(
                "/api/v1/restaurant/hours",
                headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
                json={"hours": week},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_owner_cannot_edit_another_owners_hours_or_status():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera@example.com", phone="9111111111")
            owner_b = _owner(seed, email="ownerb@example.com", phone="9222222222")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            restaurant_b_id = restaurant_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token_a}"}
            status_resp = client.patch(
                f"/api/v1/restaurant/status?restaurant_id={restaurant_b_id}", headers=headers, json={"is_open": False}
            )
            assert status_resp.status_code == 403

            hours_resp = client.get(f"/api/v1/restaurant/hours?restaurant_id={restaurant_b_id}", headers=headers)
            assert hours_resp.status_code == 403
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_status_or_hours():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9333333333", password_hash="x", role=UserRole.CUSTOMER)
            seed.add(customer)
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/restaurant/status", headers=headers).status_code == 403
            assert client.get("/api/v1/restaurant/hours", headers=headers).status_code == 403
    finally:
        _teardown(engine)
