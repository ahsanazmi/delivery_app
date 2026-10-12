"""Restaurant onboarding — the two ways a restaurant owner + restaurant get
created over HTTP:

    POST /api/v1/auth/register-restaurant  (public)  -> restaurant PENDING
    POST /api/v1/admin/restaurants          (admin)   -> restaurant APPROVED
"""

from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User, UserRole

APPLY_URL = "/api/v1/auth/register-restaurant"
ADMIN_URL = "/api/v1/admin/restaurants"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _payload(**overrides):
    payload = {
        "owner_name": "Ramesh Gupta",
        "email": "ramesh@swad.in",
        "password": "Chai@12345",
        "owner_phone": "9387650001",
        "restaurant_name": "Swad Bhojnalaya",
        "description": "Home-style thali",
        "restaurant_phone": "9387650002",
        "address": "Near Bus Stand, Shahganj, Jaunpur",
        "latitude": "26.0486",
        "longitude": "82.6847",
    }
    payload.update(overrides)
    return payload


def _admin_headers(db):
    admin = User(name="Admin", email="admin-onb@example.com", phone="9200000099", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _login(client, email, password):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_public_application_creates_pending_restaurant_owner_can_log_in(client):
    response = client.post(APPLY_URL, json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "RESTAURANT_OWNER"
    assert body["user"]["email"] == "ramesh@swad.in"
    assert body["restaurants"][0]["approval_status"] == "PENDING"
    assert "password" not in str(body).lower()

    headers = _login(client, "ramesh@swad.in", "Chai@12345")
    me = client.get("/api/v1/restaurant/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["restaurants"][0]["name"] == "Swad Bhojnalaya"
    assert me.json()["restaurants"][0]["approval_status"] == "PENDING"


def test_pending_restaurant_hidden_from_customers_until_approved(client):
    restaurant_id = client.post(APPLY_URL, json=_payload()).json()["restaurants"][0]["id"]
    assert client.get(f"/api/v1/customer/restaurants/{restaurant_id}").status_code == 404

    headers = _admin_headers(_db(client))
    approve = client.post(f"{ADMIN_URL}/{restaurant_id}/approve", headers=headers, json={"reason": "Documents verified"})
    assert approve.status_code == 200
    assert client.get(f"/api/v1/customer/restaurants/{restaurant_id}").status_code == 200


def test_public_application_rejects_duplicate_email_and_phone(client):
    assert client.post(APPLY_URL, json=_payload()).status_code == 201
    dup_email = client.post(APPLY_URL, json=_payload(owner_phone="9387650009", email="RAMESH@swad.in"))
    assert dup_email.status_code == 409
    dup_phone = client.post(APPLY_URL, json=_payload(email="other@swad.in"))
    assert dup_phone.status_code == 409


def test_public_application_validates_email_and_password(client):
    assert client.post(APPLY_URL, json=_payload(email="ramesh@swad.test")).status_code == 422
    assert client.post(APPLY_URL, json=_payload(password="short")).status_code == 422
    assert client.post(APPLY_URL, json=_payload(latitude="123")).status_code == 422


def test_public_application_cannot_escalate_role(client):
    response = client.post(APPLY_URL, json=_payload(role="ADMIN"))
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "RESTAURANT_OWNER"


def test_public_application_notifies_admins(client):
    headers = _admin_headers(_db(client))
    client.post(APPLY_URL, json=_payload())
    notifications = client.get("/api/v1/admin/notifications", headers=headers)
    assert notifications.status_code == 200
    assert "Swad Bhojnalaya" in notifications.text


def test_admin_creates_approved_restaurant_with_audit_log(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.post(ADMIN_URL, headers=headers, json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["approval_status"] == "APPROVED"
    assert body["owner_email"] == "ramesh@swad.in"
    assert client.get(f"/api/v1/customer/restaurants/{body['id']}").status_code == 200

    _login(client, "ramesh@swad.in", "Chai@12345")
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "restaurant.create"))
    assert log is not None and log.target_id == body["id"]


def test_admin_create_requires_admin(client):
    assert client.post(ADMIN_URL, json=_payload()).status_code == 401
    client.post(APPLY_URL, json=_payload())
    owner_headers = _login(client, "ramesh@swad.in", "Chai@12345")
    assert client.post(ADMIN_URL, headers=owner_headers, json=_payload(email="x@swad.in", owner_phone=None)).status_code == 403
