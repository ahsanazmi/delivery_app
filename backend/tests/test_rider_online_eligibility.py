"""Rider Portal — Phase 7: Online/Offline Status eligibility rules.

A rider can go online only if: approved, not suspended, every required
document is approved, and profile/vehicle information is complete. This
file tests each condition individually — test_rider_online_status.py covers
the approval-status side of things (PENDING/APPROVED/SUSPENDED) that Phase 6
already established.
"""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole

REQUIRED_DOCS = ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO")


def _register_and_login_rider(client, email="rider-eligibility@example.com", phone="9600000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _register_rider_without_phone(client, email="no-phone@example.com", name="No Phone"):
    """Phone is optional at registration — this is the one way a rider can
    legitimately end up without one, to exercise the profile-completeness check."""
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _make_admin(client, email="admin-eligibility@example.com", phone="9600000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _approve(client, admin_token, rider_id):
    client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "APPROVED"},
    )


def _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type):
    created = client.post(
        "/api/v1/rider/documents", headers=rider_headers,
        json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
    ).json()
    client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"}, json={"verification_status": "APPROVED"},
    )
    return created["id"]


def _set_vehicle(client, rider_headers):
    client.patch("/api/v1/rider/vehicle", headers=rider_headers, json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234"})


# --------------------------- Documents ---------------------------


def test_approved_rider_with_no_documents_cannot_go_online(client):
    token = _register_and_login_rider(client, email="no-docs@example.com", phone="9600000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _approve(client, admin_token, rider_id)

    response = client.patch("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": True})
    assert response.status_code == 403
    assert "driving license" in response.json()["detail"].lower()


def test_missing_a_single_required_document_still_blocks_going_online(client):
    token = _register_and_login_rider(client, email="missing-one-doc@example.com", phone="9600000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-eligibility@example.com", phone="9600000098")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    # Approve every required document except PROFILE_PHOTO.
    for doc_type in ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT"):
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403
    assert "profile photo" in response.json()["detail"].lower()


def test_a_pending_unreviewed_document_does_not_count_as_approved(client):
    token = _register_and_login_rider(client, email="pending-doc@example.com", phone="9600000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-eligibility@example.com", phone="9600000097")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in ("VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    # Driving license uploaded but never reviewed — still PENDING.
    client.post(
        "/api/v1/rider/documents", headers=rider_headers,
        json={"document_type": "DRIVING_LICENSE", "document_url": "https://example.com/license.jpg"},
    )
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403
    assert "driving license" in response.json()["detail"].lower()


def test_a_rejected_document_blocks_going_online(client):
    token = _register_and_login_rider(client, email="rejected-doc@example.com", phone="9600000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-eligibility@example.com", phone="9600000096")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in ("DRIVING_LICENSE", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    created = client.post(
        "/api/v1/rider/documents", headers=rider_headers,
        json={"document_type": "VEHICLE_REGISTRATION", "document_url": "https://example.com/reg.jpg"},
    ).json()
    client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "REJECTED", "rejection_reason": "Expired"},
    )
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403
    assert "vehicle registration" in response.json()["detail"].lower()


# --------------------------- Profile / vehicle completeness ---------------------------


def test_missing_phone_number_blocks_going_online(client):
    token = _register_rider_without_phone(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-eligibility@example.com", phone="9600000095")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in REQUIRED_DOCS:
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403
    assert "phone" in response.json()["detail"].lower()


def test_missing_vehicle_info_blocks_going_online(client):
    token = _register_and_login_rider(client, email="no-vehicle@example.com", phone="9600000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-eligibility@example.com", phone="9600000094")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in REQUIRED_DOCS:
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    # Vehicle info deliberately left unset.

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 403
    assert "vehicle" in response.json()["detail"].lower()


def test_completing_every_condition_finally_allows_going_online(client):
    token = _register_and_login_rider(client, email="fully-eligible@example.com", phone="9600000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin7-eligibility@example.com", phone="9600000093")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in REQUIRED_DOCS:
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 200
    assert response.json()["is_online"] is True


def test_bank_document_is_not_required_to_go_online(client):
    """Bank document gates payouts, not dispatch eligibility — a fully
    eligible rider must not be blocked just because it's missing."""
    token = _register_and_login_rider(client, email="no-bank-doc@example.com", phone="9600000017")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin8-eligibility@example.com", phone="9600000092")
    _approve(client, admin_token, rider_id)
    rider_headers = {"Authorization": f"Bearer {token}"}

    for doc_type in REQUIRED_DOCS:  # BANK_DOCUMENT intentionally excluded
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    _set_vehicle(client, rider_headers)

    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 200


# --------------------------- GET /status proactively reports eligibility ---------------------------


def test_get_status_reports_can_go_online_and_reason_before_any_patch_attempt(client):
    token = _register_and_login_rider(client, email="proactive-check@example.com", phone="9600000018")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin9-eligibility@example.com", phone="9600000091")
    _approve(client, admin_token, rider_id)

    before = client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}).json()
    assert before["can_go_online"] is False
    assert "driving license" in before["online_blocked_reason"].lower()

    rider_headers = {"Authorization": f"Bearer {token}"}
    for doc_type in REQUIRED_DOCS:
        _upload_and_approve_document(client, admin_token, rider_headers, rider_id, doc_type)
    _set_vehicle(client, rider_headers)

    after = client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}).json()
    assert after["can_go_online"] is True
    assert after["online_blocked_reason"] is None
