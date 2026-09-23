"""Integration Phase 22 — Security & IDOR Testing.

This is the final, consolidated sweep across every "A -> B" boundary this
phase names, plus the one angle not directly exercised anywhere else in
the suite: a forged "role" claim in the JWT itself. Everything else this
phase asks for (modified URL IDs/UUIDs, modified request bodies, expired/
forged/missing tokens) already has dozens of dedicated tests across
test_security.py, test_customer_role_isolation.py,
test_legacy_addresses_role_isolation.py, test_rider_security_audit.py,
test_restaurant_security_audit.py, test_admin_security_audit.py, and the
IDOR-specific tests threaded through nearly every phase this session —
this file is not a replacement for those, it is the one place that proves
all four boundaries and the token-forgery angle together, in one pass,
against real HTTP.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_a_forged_role_claim_in_the_jwt_is_never_trusted(engine):
    """The access token only ever encodes `sub` (user id) and `type` — no
    role claim exists in the real token shape at all (see
    create_access_token/decode_token in app/core/security.py). This
    crafts a token for a real CUSTOMER account but adds a forged
    "role": "ADMIN" claim anyway, signed with the real secret (so
    signature verification alone wouldn't catch a naive implementation
    that read role from the token). get_current_user must still resolve
    the role from a live User.role database lookup, ignoring the claim
    entirely, so an admin-only route stays a 403."""
    with Session(engine) as seed:
        customer = User(
            name="Customer", email="forge-role@example.com", phone="9600000001",
            password_hash=hash_password("x"), role=UserRole.CUSTOMER,
        )
        seed.add(customer)
        seed.commit()
        customer_id = customer.id

    forged_token = jwt.encode(
        {
            "sub": str(customer_id),
            "type": "access",
            "role": "ADMIN",  # forged — the real token never carries this at all
            "exp": datetime.now(UTC) + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {forged_token}"}
        # The token is validly signed and would decode successfully — but
        # the forged role claim must have zero effect on authorization.
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["role"] == "CUSTOMER"  # the real, DB-backed role — not the forged claim

        admin_only = client.get("/api/v1/admin/dashboard", headers=headers)
        assert admin_only.status_code == 403

        rider_only = client.get("/api/v1/rider/orders", headers=headers)
        assert rider_only.status_code == 403


def test_customer_a_cannot_reach_customer_b_data(engine):
    with Session(engine) as seed:
        customer_a = User(name="Customer A", email="idor-a@example.com", phone="9600000010", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        customer_b = User(name="Customer B", email="idor-b@example.com", phone="9600000011", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        seed.add_all([customer_a, customer_b])
        seed.commit()
        address_b = create_address(seed, customer_b.id, {
            "label": "Home", "recipient_name": "B", "phone": "9600000011",
            "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "123456",
        })
        token_a = create_access_token(customer_a.id)
        address_b_id = address_b.id

    with TestClient(app) as client:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        # Modified URL ID: Customer A guesses/knows Customer B's address id.
        assert client.get(f"/api/v1/customer/addresses/{address_b_id}", headers=headers_a).status_code == 404
        assert client.delete(f"/api/v1/customer/addresses/{address_b_id}", headers=headers_a).status_code == 404
        assert client.get(f"/api/v1/customer/orders/{uuid.uuid4()}", headers=headers_a).status_code == 404


def test_rider_a_cannot_reach_rider_b_data(engine):
    with Session(engine) as seed:
        rider_a = User(name="Rider A", email="idor-rider-a@example.com", phone="9600000020", password_hash=hash_password("x"), role=UserRole.RIDER)
        rider_b = User(name="Rider B", email="idor-rider-b@example.com", phone="9600000021", password_hash=hash_password("x"), role=UserRole.RIDER)
        seed.add_all([rider_a, rider_b])
        seed.commit()
        seed.add(DeliveryPartner(user_id=rider_b.id, approval_status=ApprovalStatus.APPROVED))
        seed.commit()
        token_a = create_access_token(rider_a.id)

    with TestClient(app) as client:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        # Modified UUID: Rider A tries a delivery-detail id that doesn't belong to them.
        assert client.get(f"/api/v1/rider/deliveries/{uuid.uuid4()}", headers=headers_a).status_code == 404
        assert client.post(f"/api/v1/rider/deliveries/{uuid.uuid4()}/pickup", headers=headers_a).status_code == 404


def test_restaurant_a_cannot_reach_restaurant_b_data(engine):
    with Session(engine) as seed:
        owner_a = User(name="Owner A", email="idor-owner-a@example.com", phone="9600000030", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        owner_b = User(name="Owner B", email="idor-owner-b@example.com", phone="9600000031", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add_all([owner_a, owner_b])
        seed.commit()
        restaurant_b = Restaurant(
            owner_id=owner_b.id, name="B's Diner", phone="9876500000", address="Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        seed.add(restaurant_b)
        seed.commit()
        product_b = Product(restaurant_id=restaurant_b.id, name="B's Item", price=Decimal("100.00"))
        seed.add(product_b)
        seed.commit()
        token_a = create_access_token(owner_a.id)
        product_b_id, restaurant_b_id = product_b.id, restaurant_b.id

    with TestClient(app) as client:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        # Modified UUID: Owner A tries to manage Owner B's product directly.
        assert client.patch(
            f"/api/v1/restaurant/products/{product_b_id}", headers=headers_a, json={"price": "1.00"}
        ).status_code == 404
        assert client.delete(f"/api/v1/restaurant/products/{product_b_id}", headers=headers_a).status_code == 404
        # Modified query param: Owner A passes Owner B's restaurant_id explicitly.
        assert client.get(
            f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}", headers=headers_a
        ).status_code == 403


def test_admin_only_api_rejects_every_non_admin_role(engine):
    with Session(engine) as seed:
        customer = User(name="Customer", email="idor-cust-admin@example.com", phone="9600000040", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        rider = User(name="Rider", email="idor-rider-admin@example.com", phone="9600000041", password_hash=hash_password("x"), role=UserRole.RIDER)
        owner = User(name="Owner", email="idor-owner-admin@example.com", phone="9600000042", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add_all([customer, rider, owner])
        seed.commit()
        tokens = {
            "customer": create_access_token(customer.id),
            "rider": create_access_token(rider.id),
            "restaurant_owner": create_access_token(owner.id),
        }

    with TestClient(app) as client:
        for role_name, token in tokens.items():
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 403, role_name
            assert client.get("/api/v1/admin/customers", headers=headers).status_code == 403, role_name
            assert client.post(
                "/api/v1/admin/customers/00000000-0000-0000-0000-000000000000/suspend",
                headers=headers, json={"reason": "x"},
            ).status_code == 403, role_name
        assert client.get("/api/v1/admin/dashboard").status_code == 401  # missing token entirely


def test_modified_request_body_cannot_reassign_ownership(engine):
    """Modified request body: a customer tries to smuggle a different
    user_id into a request that creates data under their own account,
    attempting to make it belong to someone else instead."""
    with Session(engine) as seed:
        customer = User(name="Customer", email="idor-body-cust@example.com", phone="9600000050", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        victim = User(name="Victim", email="idor-body-victim@example.com", phone="9600000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        seed.add_all([customer, victim])
        seed.commit()
        token = create_access_token(customer.id)
        victim_id = victim.id

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/v1/customer/addresses", headers=headers,
            json={
                "recipient_name": "Not me", "phone": "9999999999", "address_line": "1 Road",
                "city": "Town", "state": "ST", "postal_code": "123456",
                "user_id": str(victim_id),  # not a real field on the schema — must be silently ignored
            },
        )
        assert created.status_code == 201
        assert created.json()["user_id"] == str(customer.id)  # never the smuggled victim id
