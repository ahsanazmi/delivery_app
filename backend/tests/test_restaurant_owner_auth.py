"""Restaurant Owner Portal — Phase 1: authentication & authorization.

Covers the shared-auth flow working for RESTAURANT_OWNER, GET /api/v1/restaurant/me,
and the owner-to-restaurant isolation rule (Owner A cannot see Owner B's data).
"""

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
    user = User(
        name="Restaurant Owner",
        email=email,
        phone=phone,
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.RESTAURANT_OWNER,
    )
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House", is_active=True):
    restaurant = Restaurant(
        owner_id=owner.id,
        name=name,
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("0.00"),
        is_active=is_active,
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


def test_restaurant_owner_role_survives_the_migration_rename(db):
    owner = _owner(db)
    assert owner.role == UserRole.RESTAURANT_OWNER
    assert owner.role.value == "RESTAURANT_OWNER"


def test_restaurant_owner_full_auth_flow_over_http():
    """Login, /auth/me, refresh, and logout all work for RESTAURANT_OWNER
    using the same shared endpoints every other role uses — no separate
    auth system."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            _owner(seed, email="flow@example.com", phone="9111111111")

        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login", json={"email": "flow@example.com", "password": "Passw0rd!"}
            )
            assert login.status_code == 200
            tokens = login.json()

            me = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            assert me.status_code == 200
            assert me.json()["role"] == "RESTAURANT_OWNER"

            refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            assert refreshed.status_code == 200
            assert "access_token" in refreshed.json()

            logout = client.post(
                "/api/v1/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            assert logout.status_code == 200
    finally:
        _teardown(engine)


def test_restaurant_me_returns_owners_own_restaurants_only():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera@example.com", phone="9111111111")
            owner_b = _owner(seed, email="ownerb@example.com", phone="9222222222")
            _restaurant(seed, owner_a, name="A's Diner")
            _restaurant(seed, owner_a, name="A's Second Spot")
            _restaurant(seed, owner_b, name="B's Diner")
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token_a}"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["user"]["role"] == "RESTAURANT_OWNER"
            names = {r["name"] for r in body["restaurants"]}
            assert names == {"A's Diner", "A's Second Spot"}
            assert "B's Diner" not in names
    finally:
        _teardown(engine)


def test_restaurant_me_includes_deactivated_restaurants_for_the_owner():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner, name="Still Active")
            _restaurant(seed, owner, name="Temporarily Closed", is_active=False)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            names = {r["name"] for r in response.json()["restaurants"]}
            assert names == {"Still Active", "Temporarily Closed"}
    finally:
        _teardown(engine)


def test_restaurant_me_with_no_restaurants_returns_empty_list():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["restaurants"] == []
    finally:
        _teardown(engine)


def test_customer_cannot_access_restaurant_portal():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(
                name="Customer", email="cust@example.com", phone="9333333333",
                password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER,
            )
            seed.add(customer)
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_rider_cannot_access_restaurant_portal():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            rider = User(
                name="Rider", email="rider@example.com", phone="9444444444",
                password_hash=hash_password("Passw0rd!"), role=UserRole.RIDER,
            )
            seed.add(rider)
            seed.commit()
            token = create_access_token(rider.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_admin_does_not_automatically_become_a_restaurant_owner():
    """Admin has its own /admin/* surface — it must not be silently treated
    as a restaurant owner just because it's a privileged role."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            admin = User(
                name="Admin", email="admin@example.com", phone="9555555555",
                password_hash=hash_password("Passw0rd!"), role=UserRole.ADMIN,
            )
            seed.add(admin)
            seed.commit()
            token = create_access_token(admin.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_owner_cannot_update_another_owners_restaurant():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera2@example.com", phone="9666666666")
            owner_b = _owner(seed, email="ownerb2@example.com", phone="9777777777")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            restaurant_b_id = restaurant_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/restaurants/{restaurant_b_id}",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"name": "Hijacked Name"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_unauthenticated_request_to_restaurant_me_is_rejected():
    engine = _http_setup()
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/restaurant/me").status_code == 401
    finally:
        _teardown(engine)


def test_restaurant_owner_login_rejects_wrong_password():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            _owner(seed, email="wrongpass-owner@example.com", phone="9888888881")

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login", json={"email": "wrongpass-owner@example.com", "password": "not-the-password"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_deactivated_restaurant_owner_cannot_login():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed, email="deactivated-owner@example.com", phone="9888888882")
            owner.is_active = False
            seed.commit()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login", json={"email": "deactivated-owner@example.com", "password": "Passw0rd!"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_restaurant_owner_with_an_expired_token_is_rejected():
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.core.config import settings

    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed, email="expired-owner@example.com", phone="9888888883")
            owner_id = owner.id

        expired = jwt.encode(
            {"sub": str(owner_id), "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        with TestClient(app) as client:
            response = client.get("/api/v1/restaurant/me", headers={"Authorization": f"Bearer {expired}"})
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_restaurant_owner_route_rejects_an_invalid_token():
    engine = _http_setup()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/restaurant/me", headers={"Authorization": "Bearer garbage-token"})
            assert response.status_code == 401
    finally:
        _teardown(engine)
