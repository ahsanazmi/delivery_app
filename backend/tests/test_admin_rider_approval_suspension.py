"""Admin Portal — Phase 9: Rider Approval & Suspension (final account control).

Verifies the three business rules from the phase brief, exercised through
the new dedicated endpoints:

    PENDING rider   -> cannot go online
    APPROVED rider  -> can go online
    SUSPENDED rider -> cannot accept deliveries, and suspension is
                       enforced immediately (no re-login / token refresh).
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

RIDERS_URL = "/api/v1/admin/riders"
_REQUIRED_DOCS = ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO")


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p9@example.com", phone="9600000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _make_rider_with_token(db, *, name, email, phone):
    rider = _make_user(db, name=name, email=email, phone=phone, role=UserRole.RIDER)
    return rider, create_access_token(rider.id)


def _make_rider_fully_eligible(client, admin_headers, rider_headers, rider_id):
    """Beyond APPROVED, going online also requires every required document
    approved and vehicle info set (Rider Portal Phase 7) — satisfied here so
    tests that need a genuinely online-eligible rider aren't blocked by
    unrelated eligibility rules this phase isn't about."""
    for doc_type in _REQUIRED_DOCS:
        created = client.post(
            "/api/v1/rider/documents", headers=rider_headers,
            json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
        ).json()
        client.patch(
            f"{RIDERS_URL}/{rider_id}/documents/{created['id']}", headers=admin_headers,
            json={"verification_status": "APPROVED"},
        )
    client.patch(
        "/api/v1/rider/vehicle", headers=rider_headers,
        json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234"},
    )


def _make_available_order(db):
    order = Order(
        user_id=uuid.uuid4(), customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.READY_FOR_PICKUP,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", state="TS", postal_code="123456",
        latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_dedicated_endpoints_require_admin(client):
    db = _db(client)
    rider, rider_token = _make_rider_with_token(db, name="Auth Rider", email="auth-rider-p9@example.com", phone="9600000010")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    assert client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=rider_headers, json={"reason": "test"}).status_code == 403
    assert client.post(f"{RIDERS_URL}/{rider.id}/reject", headers=rider_headers, json={"rejection_reason": "x"}).status_code == 403
    assert client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=rider_headers, json={"reason": "test"}).status_code == 403
    assert client.post(f"{RIDERS_URL}/{rider.id}/activate", headers=rider_headers, json={"reason": "test"}).status_code == 403

    assert client.post(f"{RIDERS_URL}/{rider.id}/approve").status_code == 401


def test_pending_rider_cannot_go_online(client):
    db = _db(client)
    rider, rider_token = _make_rider_with_token(db, name="Pending Rider", email="pending-rider-p9@example.com", phone="9600000020")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403


def test_rejected_rider_cannot_go_online(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, rider_token = _make_rider_with_token(db, name="Rejected Rider", email="rejected-rider-p9@example.com", phone="9600000030")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    reject = client.post(f"{RIDERS_URL}/{rider.id}/reject", headers=headers, json={"rejection_reason": "Incomplete application"})
    assert reject.status_code == 200
    assert reject.json()["approval_status"] == "REJECTED"

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403


def test_approved_and_eligible_rider_can_go_online(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, rider_token = _make_rider_with_token(db, name="Approved Rider", email="approved-rider-p9@example.com", phone="9600000040")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    approve = client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"})
    assert approve.status_code == 200
    assert approve.json()["approval_status"] == "APPROVED"

    _make_rider_fully_eligible(client, headers, rider_headers, rider.id)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 200
    assert response.json()["is_online"] is True


def test_suspend_enforces_immediately_forces_offline_and_blocks_new_accepts(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, rider_token = _make_rider_with_token(db, name="Suspend Rider", email="suspend-rider-p9@example.com", phone="9600000050")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"})
    _make_rider_fully_eligible(client, headers, rider_headers, rider.id)
    online = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert online.json()["is_online"] is True

    suspend = client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "test"})
    assert suspend.status_code == 200
    body = suspend.json()
    assert body["approval_status"] == "SUSPENDED"
    assert body["is_online"] is False

    # Enforced immediately — the rider's own existing token still works,
    # no re-login/refresh happened, yet they read as offline right away.
    status_check = client.get("/api/v1/rider/status", headers=rider_headers)
    assert status_check.json()["is_online"] is False

    # Cannot accept a brand-new delivery either, in the very same session.
    order = _make_available_order(db)
    accept = client.post(f"/api/v1/rider/deliveries/{order.id}/accept", headers=rider_headers)
    assert accept.status_code == 403


def test_suspended_rider_cannot_go_back_online(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, rider_token = _make_rider_with_token(db, name="Retry Online Rider", email="retry-online-rider-p9@example.com", phone="9600000060")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"})
    _make_rider_fully_eligible(client, headers, rider_headers, rider.id)
    client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "test"})

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403


def test_activate_from_suspended_restores_ability_to_go_online(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, rider_token = _make_rider_with_token(db, name="Reinstated Rider", email="reinstated-rider-p9@example.com", phone="9600000070")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"})
    _make_rider_fully_eligible(client, headers, rider_headers, rider.id)
    client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "test"})

    activate = client.post(f"{RIDERS_URL}/{rider.id}/activate", headers=headers, json={"reason": "test"})
    assert activate.status_code == 200
    assert activate.json()["approval_status"] == "APPROVED"

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 200
    assert response.json()["is_online"] is True


def test_reject_requires_reason(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, _ = _make_rider_with_token(db, name="No Reason Rider", email="no-reason-rider-p9@example.com", phone="9600000080")

    response = client.post(f"{RIDERS_URL}/{rider.id}/reject", headers=headers, json={})
    assert response.status_code == 422


def test_invalid_transitions_via_dedicated_endpoints_are_conflicts(client):
    db = _db(client)
    headers = _admin_headers(db)
    pending_rider, _ = _make_rider_with_token(db, name="Invalid Transition Rider", email="invalid-transition-p9@example.com", phone="9600000090")

    assert client.post(f"{RIDERS_URL}/{pending_rider.id}/suspend", headers=headers, json={"reason": "test"}).status_code == 409
    assert client.post(f"{RIDERS_URL}/{pending_rider.id}/activate", headers=headers, json={"reason": "test"}).status_code == 409

    client.post(f"{RIDERS_URL}/{pending_rider.id}/approve", headers=headers, json={"reason": "test"})
    assert client.post(f"{RIDERS_URL}/{pending_rider.id}/approve", headers=headers, json={"reason": "test"}).status_code == 409
    assert client.post(f"{RIDERS_URL}/{pending_rider.id}/reject", headers=headers, json={"rejection_reason": "x"}).status_code == 409


def test_full_lifecycle_via_dedicated_endpoints(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider, _ = _make_rider_with_token(db, name="Full Lifecycle Rider P9", email="full-lifecycle-p9@example.com", phone="9600000100")

    approve = client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"})
    assert approve.json()["approval_status"] == "APPROVED"

    suspend = client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "test"})
    assert suspend.json()["approval_status"] == "SUSPENDED"

    activate = client.post(f"{RIDERS_URL}/{rider.id}/activate", headers=headers, json={"reason": "test"})
    assert activate.json()["approval_status"] == "APPROVED"
