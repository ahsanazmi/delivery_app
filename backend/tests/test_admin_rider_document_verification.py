"""Admin Portal — Phase 8: Rider Document Verification."""

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.rider_document import DocumentVerificationStatus, RiderDocument
from app.models.user import User, UserRole

RIDERS_URL = "/api/v1/admin/riders"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p8@example.com", phone="9000000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _make_document(db, *, rider_id, document_type="DRIVING_LICENSE", verification_status=DocumentVerificationStatus.PENDING):
    document = RiderDocument(
        rider_id=rider_id, document_type=document_type, document_url="https://example.com/doc.jpg",
        verification_status=verification_status,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_list_documents_requires_admin(client):
    db = _db(client)
    rider = _make_user(db, name="Some Rider", email="some-rider-p8@example.com", phone="9000000010", role=UserRole.RIDER)
    token = create_access_token(rider.id)
    assert client.get(f"{RIDERS_URL}/{rider.id}/documents", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(f"{RIDERS_URL}/{rider.id}/documents").status_code == 401


def test_list_documents_returns_all_for_rider(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Doc Rider", email="doc-rider-p8@example.com", phone="9000000020", role=UserRole.RIDER)
    _make_document(db, rider_id=rider.id, document_type="DRIVING_LICENSE")
    _make_document(db, rider_id=rider.id, document_type="VEHICLE_REGISTRATION")
    _make_document(db, rider_id=rider.id, document_type="IDENTITY_DOCUMENT")

    response = client.get(f"{RIDERS_URL}/{rider.id}/documents", headers=headers)
    assert response.status_code == 200
    types = {doc["document_type"] for doc in response.json()}
    assert types == {"DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT"}


def test_list_documents_404_for_non_rider_or_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Not A Rider P8", email="not-rider-p8@example.com", phone="9000000030", role=UserRole.CUSTOMER)

    assert client.get(f"{RIDERS_URL}/{customer.id}/documents", headers=headers).status_code == 404
    assert client.get(f"{RIDERS_URL}/00000000-0000-0000-0000-000000000000/documents", headers=headers).status_code == 404


def test_approve_from_pending_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Approve Doc Rider", email="approve-doc-p8@example.com", phone="9000000040", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id)

    response = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers=headers)
    assert response.status_code == 200
    assert response.json()["verification_status"] == "APPROVED"


def test_approve_from_rejected_succeeds_and_clears_reason(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Reconsider Doc Rider", email="reconsider-doc-p8@example.com", phone="9000000050", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id, verification_status=DocumentVerificationStatus.REJECTED)
    db.query(RiderDocument).filter(RiderDocument.id == document.id).update({"rejection_reason": "blurry photo"})
    db.commit()

    response = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["verification_status"] == "APPROVED"
    assert body["rejection_reason"] is None


def test_approve_already_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Already Approved Doc Rider", email="already-approved-doc-p8@example.com", phone="9000000060", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id, verification_status=DocumentVerificationStatus.APPROVED)

    response = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers=headers)
    assert response.status_code == 409


def test_reject_requires_reason_and_succeeds_from_pending(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Reject Doc Rider", email="reject-doc-p8@example.com", phone="9000000070", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id)

    missing = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject", headers=headers, json={})
    assert missing.status_code == 422

    response = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject", headers=headers, json={"rejection_reason": "Illegible"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification_status"] == "REJECTED"
    assert body["rejection_reason"] == "Illegible"


def test_reject_from_approved_succeeds(client):
    """Documents have no 'suspended' state — an admin reconsidering a
    previously-approved document goes straight to REJECTED."""
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Revoke Doc Rider", email="revoke-doc-p8@example.com", phone="9000000080", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id, verification_status=DocumentVerificationStatus.APPROVED)

    response = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject", headers=headers, json={"rejection_reason": "Discovered forged"}
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "REJECTED"


def test_reject_already_rejected_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Already Rejected Doc Rider", email="already-rejected-doc-p8@example.com", phone="9000000090", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id, verification_status=DocumentVerificationStatus.REJECTED)

    response = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject", headers=headers, json={"rejection_reason": "x"}
    )
    assert response.status_code == 409


def test_actions_404_for_document_of_different_rider(client):
    """A document scoped to Rider A must not be reachable through Rider B's path."""
    db = _db(client)
    headers = _admin_headers(db)
    rider_a = _make_user(db, name="Rider A Doc", email="rider-a-doc-p8@example.com", phone="9000000100", role=UserRole.RIDER)
    rider_b = _make_user(db, name="Rider B Doc", email="rider-b-doc-p8@example.com", phone="9000000101", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider_a.id)

    response = client.post(f"{RIDERS_URL}/{rider_b.id}/documents/{document.id}/approve", headers=headers)
    assert response.status_code == 404


def test_actions_require_admin(client):
    db = _db(client)
    rider = _make_user(db, name="Auth Doc Rider", email="auth-doc-p8@example.com", phone="9000000110", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id)
    rider_token = create_access_token(rider.id)

    approve = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers={"Authorization": f"Bearer {rider_token}"}
    )
    assert approve.status_code == 403

    reject = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject",
        headers={"Authorization": f"Bearer {rider_token}"},
        json={"rejection_reason": "x"},
    )
    assert reject.status_code == 403

    assert client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve").status_code == 401


def test_full_document_lifecycle_pending_approved_rejected_approved(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Lifecycle Doc Rider", email="lifecycle-doc-p8@example.com", phone="9000000120", role=UserRole.RIDER)
    document = _make_document(db, rider_id=rider.id)

    r1 = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers=headers)
    assert r1.json()["verification_status"] == "APPROVED"

    r2 = client.post(
        f"{RIDERS_URL}/{rider.id}/documents/{document.id}/reject", headers=headers, json={"rejection_reason": "reconsidered"}
    )
    assert r2.json()["verification_status"] == "REJECTED"

    r3 = client.post(f"{RIDERS_URL}/{rider.id}/documents/{document.id}/approve", headers=headers)
    assert r3.json()["verification_status"] == "APPROVED"
