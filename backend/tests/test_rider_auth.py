"""Rider Portal — Phase 1: Rider Authentication & Authorization.

The rider app uses the same shared /api/v1/auth/* endpoints every other role
uses (register, login, refresh, logout, me) — there is no separate rider
auth system. This file covers the phase's explicit checklist: full auth flow
for a RIDER account, the require_rider() dependency gate, and the security
requirement that a Customer/Restaurant Owner/Admin cannot gain rider access
by manipulating the frontend (the backend must reject them regardless of
what a client claims).
"""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _make_user(client, role: UserRole, email: str, phone: str) -> str:
    """Seed a user directly (bypassing /auth/register's role allow-list,
    which is exactly the point for RESTAURANT_OWNER/ADMIN — those roles
    can't self-register at all) and return an access token for them."""
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = User(name="Test User", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=role)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return token


def test_full_rider_auth_flow_over_http(client):
    """Register, login, /auth/me, refresh, and logout all work for RIDER
    using the shared endpoints — no separate auth system for riders."""
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Ravi Kumar",
            "email": "ravi.rider@example.com",
            "password": "secure-pass-123",
            "phone": "9123456780",
            "role": "RIDER",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "RIDER"
    assert "password_hash" not in registration.text

    login = client.post(
        "/api/v1/auth/login", json={"email": "ravi.rider@example.com", "password": "secure-pass-123"}
    )
    assert login.status_code == 200
    tokens = login.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "RIDER"
    assert me.json()["email"] == "ravi.rider@example.com"

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert "access_token" in refreshed.json()
    assert refreshed.json()["access_token"] != tokens["access_token"]

    # The refreshed access token is itself valid against a protected endpoint.
    me_again = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    )
    assert me_again.status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert logout.status_code == 200


def test_rider_login_rejects_wrong_password(client):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Ravi Kumar", "email": "wrongpass@example.com", "password": "secure-pass-123", "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": "wrongpass@example.com", "password": "not-the-password"})
    assert login.status_code == 401


def test_expired_or_garbage_refresh_token_is_rejected(client):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401


def test_unauthenticated_request_to_rider_endpoint_is_rejected(client):
    response = client.get("/api/v1/rider/orders")
    assert response.status_code == 401


def test_rider_endpoint_rejects_customer_restaurant_owner_and_admin_tokens(client):
    """The core security requirement of this phase: a Customer, Restaurant
    Owner, or Admin must not gain Rider access merely by having a valid
    token — the backend checks the *actual* stored role on every request,
    never anything the client asserts about itself."""
    for role, email, phone in (
        (UserRole.CUSTOMER, "cust-probe@example.com", "9100000001"),
        (UserRole.RESTAURANT_OWNER, "owner-probe@example.com", "9100000002"),
        (UserRole.ADMIN, "admin-probe@example.com", "9100000003"),
    ):
        token = _make_user(client, role, email, phone)
        response = client.get("/api/v1/rider/orders", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, f"{role} should not reach a rider endpoint"


def test_rider_token_is_accepted_by_rider_endpoints(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Ravi Kumar", "email": "realrider@example.com", "password": "secure-pass-123", "role": "RIDER"},
    )
    assert registration.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": "realrider@example.com", "password": "secure-pass-123"})
    token = login.json()["access_token"]

    response = client.get("/api/v1/rider/orders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_deactivated_rider_account_is_rejected_even_with_a_valid_token(client):
    """An expired-session-adjacent case: if the account itself is deactivated
    (e.g. suspended by an admin) between token issuance and use, the token
    must stop working immediately, not remain valid until it naturally expires."""
    from app.db.session import get_db

    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Ravi Kumar", "email": "deactivated-rider@example.com", "password": "secure-pass-123", "role": "RIDER"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": "deactivated-rider@example.com", "password": "secure-pass-123"}
    )
    token = login.json()["access_token"]

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = db.query(User).filter(User.email == "deactivated-rider@example.com").first()
    user.is_active = False
    db.commit()
    db.close()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_malformed_or_missing_bearer_token_is_rejected(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage-token"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "NotBearer sometoken"}).status_code == 401


def test_rider_with_a_genuinely_expired_access_token_is_rejected(client):
    """Unlike test_expired_or_garbage_refresh_token_is_rejected (a malformed
    refresh token), this is a real, correctly-signed access token whose exp
    claim has already passed."""
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.core.config import settings

    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Ravi Kumar", "email": "expired-rider@example.com", "password": "secure-pass-123", "role": "RIDER"},
    )
    assert registration.status_code == 201
    rider_id = registration.json()["id"]

    expired = jwt.encode(
        {"sub": rider_id, "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = client.get("/api/v1/rider/orders", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
