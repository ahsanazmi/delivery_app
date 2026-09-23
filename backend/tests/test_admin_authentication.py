"""Admin Portal — Phase 31: Complete Admin Testing — Authentication.

Every other admin test file constructs an admin's JWT directly via
create_access_token() as test setup, which is correct for testing *what
the token authorizes* but never actually exercises the real
login/refresh/logout HTTP endpoints with an admin identity end to end.
This file closes that specific gap: an admin, provisioned the only way
this platform allows (never self-registered — see test_auth.py's own
test_register_rejects_restaurant_owner_and_admin_roles), goes through the
real /api/v1/auth/* endpoints.

Wrong-role and IDOR coverage across the full admin route surface already
lives in test_admin_security_audit.py (Phase 25); this file's "wrong role"
and "expired token" tests are the admin-identity-specific slice of that
same guarantee, not a duplicate of it.
"""

from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole

DASHBOARD_URL = "/api/v1/admin/dashboard"
ADMIN_PASSWORD = "Admin-Secure-Pass-1"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_admin(db, *, email="admin-auth-p31@example.com", phone="7600000001", is_active=True):
    admin = User(
        name="Admin", email=email, phone=phone, password_hash=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN, is_active=is_active,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def test_admin_can_login_via_the_real_endpoint_and_use_the_token(client):
    db = _db(client)
    admin = _make_admin(db)

    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD})
    assert login.status_code == 200
    body = login.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"

    dashboard = client.get(DASHBOARD_URL, headers=headers)
    assert dashboard.status_code == 200


def test_admin_login_rejects_wrong_password(client):
    db = _db(client)
    admin = _make_admin(db)

    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "not-the-password"})
    assert response.status_code == 401


def test_deactivated_admin_cannot_login(client):
    db = _db(client)
    admin = _make_admin(db, is_active=False)

    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD})
    assert response.status_code == 401


def test_admin_can_refresh_their_token(client):
    db = _db(client)
    admin = _make_admin(db)
    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD})
    refresh_token = login.json()["refresh_token"]

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    new_access_token = refreshed.json()["access_token"]

    dashboard = client.get(DASHBOARD_URL, headers={"Authorization": f"Bearer {new_access_token}"})
    assert dashboard.status_code == 200


def test_admin_refresh_endpoint_rejects_an_access_token_used_as_a_refresh_token(client):
    db = _db(client)
    admin = _make_admin(db)

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": create_access_token(admin.id)})
    assert response.status_code == 401


def test_deactivated_admins_existing_refresh_token_stops_working(client):
    """Suspending an admin (Phase 23's account-status action, on any role)
    must close the refresh path too, not just block new logins."""
    db = _db(client)
    admin = _make_admin(db)
    refresh_token = create_refresh_token(admin.id)

    admin.is_active = False
    db.commit()

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


def test_admin_can_logout(client):
    db = _db(client)
    admin = _make_admin(db)
    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 200


def test_logout_requires_authentication(client):
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401


def test_non_admin_with_a_valid_unexpired_token_is_rejected_from_admin_routes(client):
    """The admin-identity-specific slice of the "wrong role" guarantee —
    see test_admin_security_audit.py for the exhaustive, all-72-routes
    version of this same check."""
    db = _db(client)
    customer = User(name="Not Admin", email="not-admin-auth-p31@example.com", phone="7600000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    db.refresh(customer)

    response = client.get(DASHBOARD_URL, headers={"Authorization": f"Bearer {create_access_token(customer.id)}"})
    assert response.status_code == 403


def test_admin_with_an_expired_token_is_rejected(client):
    db = _db(client)
    admin = _make_admin(db)

    expired = jwt.encode(
        {"sub": str(admin.id), "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = client.get(DASHBOARD_URL, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_admin_with_a_tampered_token_is_rejected(client):
    db = _db(client)
    admin = _make_admin(db)
    token = create_access_token(admin.id)

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    response = client.get(DASHBOARD_URL, headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_unauthenticated_request_to_admin_route_is_rejected(client):
    response = client.get(DASHBOARD_URL)
    assert response.status_code == 401
