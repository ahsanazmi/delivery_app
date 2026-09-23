"""Restaurant Owner Portal — Phase 3: restaurant profile."""

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
from app.models import Restaurant, User, UserRole


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


def _restaurant(db, owner, name="Chai House"):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("100.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


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


def test_get_profile_returns_owners_restaurant():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/profile", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["name"] == "Chai House"
            assert body["email"] is None
    finally:
        _teardown(engine)


def test_patch_profile_updates_all_editable_fields():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "Chai House Deluxe",
                    "description": "Now with more chai.",
                    "phone": "9123456780",
                    "email": "contact@chaihouse.example.com",
                    "address": "42 New Road, Bengaluru",
                    "latitude": "12.9800",
                    "longitude": "77.6000",
                    "minimum_order": "150.00",
                    "delivery_fee": "40.00",
                    "logo_url": "https://example.com/logo.png",
                    "cover_image_url": "https://example.com/cover.png",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["name"] == "Chai House Deluxe"
            assert body["description"] == "Now with more chai."
            assert body["phone"] == "9123456780"
            assert body["email"] == "contact@chaihouse.example.com"
            assert body["address"] == "42 New Road, Bengaluru"
            assert body["minimum_order"] == "150.00"
            assert body["delivery_fee"] == "40.00"
            assert body["logo_url"] == "https://example.com/logo.png"
            assert body["cover_image_url"] == "https://example.com/cover.png"
    finally:
        _teardown(engine)


def test_patch_profile_partial_update_leaves_other_fields_untouched():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"delivery_fee": "50.00"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["delivery_fee"] == "50.00"
            assert body["name"] == "Chai House"  # untouched
            assert body["phone"] == "9876543210"  # untouched
    finally:
        _teardown(engine)


def test_owner_cannot_view_or_edit_another_owners_profile_via_restaurant_id():
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
            get_resp = client.get(
                f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}", headers=headers
            )
            assert get_resp.status_code == 403

            patch_resp = client.patch(
                f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}",
                headers=headers,
                json={"name": "Hijacked"},
            )
            assert patch_resp.status_code == 403
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_restaurant_profile():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9333333333", password_hash="x", role=UserRole.CUSTOMER)
            rider = User(name="R", email="r@example.com", phone="9444444444", password_hash="x", role=UserRole.RIDER)
            seed.add_all([customer, rider])
            seed.commit()
            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)

        with TestClient(app) as client:
            assert client.get(
                "/api/v1/restaurant/profile", headers={"Authorization": f"Bearer {customer_token}"}
            ).status_code == 403
            assert client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {rider_token}"},
                json={"name": "x"},
            ).status_code == 403
    finally:
        _teardown(engine)


def test_invalid_email_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"email": "not-an-email"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_invalid_image_url_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"logo_url": "not-a-url"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_negative_delivery_fee_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/restaurant/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"delivery_fee": "-10.00"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)
