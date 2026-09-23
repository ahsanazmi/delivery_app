"""Integration Phase 18 — API Contract Validation.

The real customer-mobile app manages the address book through the bare
/api/v1/addresses path (see customer-mobile/services/api/addressesApi.ts),
not /api/v1/customer/addresses. The Phase 2 role-isolation pass only
covered app/api/v1/customer/*.py and never touched this file
(app/api/v1/endpoints/addresses.py), which is a separate, parallel router
still mounted at /api/v1/addresses (see app/api/v1/router.py) — so it kept
using the bare CurrentUser dependency (any authenticated role) the whole
time, undetected because no test exercised this path at all. This file
closes that gap for the endpoint the real app actually calls.
"""

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole


def _make_user(client, role: UserRole, email: str, phone: str) -> str:
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = User(name="Test User", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=role)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return token


def test_non_customer_roles_cannot_reach_the_legacy_addresses_router(client):
    for role, email, phone in (
        (UserRole.RIDER, "legacy-addr-rider@example.com", "9700000001"),
        (UserRole.RESTAURANT_OWNER, "legacy-addr-owner@example.com", "9700000002"),
        (UserRole.ADMIN, "legacy-addr-admin@example.com", "9700000003"),
    ):
        token = _make_user(client, role, email, phone)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/addresses", headers=headers).status_code == 403, role
        assert client.post(
            "/api/v1/addresses", headers=headers,
            json={"recipient_name": "X", "phone": "9999999999", "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "123456"},
        ).status_code == 403, role


def test_customer_still_reaches_the_legacy_addresses_router(client):
    token = _make_user(client, UserRole.CUSTOMER, "legacy-addr-cust@example.com", "9700000004")
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/addresses", headers=headers,
        json={"recipient_name": "Cust", "phone": "9999999999", "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "123456"},
    )
    assert create.status_code == 201
    address_id = create.json()["id"]

    assert client.get("/api/v1/addresses", headers=headers).status_code == 200
    assert client.get(f"/api/v1/addresses/{address_id}", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/addresses/{address_id}/default", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/addresses/{address_id}", headers=headers, json={"label": "Home"}).status_code == 200
    assert client.delete(f"/api/v1/addresses/{address_id}", headers=headers).status_code == 200


def test_non_customer_roles_cannot_reach_the_legacy_reviews_create_endpoint(client):
    """Confirmed unused by any frontend app today (customer-mobile creates
    reviews via /api/v1/customer/orders/{id}/review), but hardened for
    consistency — same missed-by-Phase-2 gap as addresses.py."""
    for role, email, phone in (
        (UserRole.RIDER, "legacy-rev-rider@example.com", "9700000010"),
        (UserRole.RESTAURANT_OWNER, "legacy-rev-owner@example.com", "9700000011"),
        (UserRole.ADMIN, "legacy-rev-admin@example.com", "9700000012"),
    ):
        token = _make_user(client, role, email, phone)
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/v1/reviews", headers=headers,
            json={"target_type": "restaurant", "target_id": "00000000-0000-0000-0000-000000000000", "restaurant_id": "00000000-0000-0000-0000-000000000000", "rating": 5},
        )
        assert response.status_code == 403, role
