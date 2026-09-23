"""Rider Portal — Phase 4: Rider Documents."""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-docs@example.com", phone="9300000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _make_admin(client, email="admin-docs@example.com", phone="9300000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


# --------------------------- Rider CRUD ---------------------------


def test_new_rider_has_no_documents(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/documents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_upload_a_document(client):
    token = _register_and_login_rider(client)
    response = client.post(
        "/api/v1/rider/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_type": "DRIVING_LICENSE",
            "document_url": "https://example.com/license.jpg",
            "document_number": "DL-1234567",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "DRIVING_LICENSE"
    assert body["document_url"] == "https://example.com/license.jpg"
    assert body["document_number"] == "DL-1234567"
    assert body["verification_status"] == "PENDING"
    assert body["rejection_reason"] is None


def test_document_url_must_be_a_valid_url(client):
    token = _register_and_login_rider(client)
    response = client.post(
        "/api/v1/rider/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_type": "PROFILE_PHOTO", "document_url": "not-a-url"},
    )
    assert response.status_code == 422


def test_document_number_is_optional(client):
    token = _register_and_login_rider(client)
    response = client.post(
        "/api/v1/rider/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_type": "PROFILE_PHOTO", "document_url": "https://example.com/photo.jpg"},
    )
    assert response.status_code == 201
    assert response.json()["document_number"] is None


def test_uploading_the_same_document_type_twice_is_rejected(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"document_type": "IDENTITY_DOCUMENT", "document_url": "https://example.com/id.jpg"}
    first = client.post("/api/v1/rider/documents", headers=headers, json=payload)
    assert first.status_code == 201

    second = client.post(
        "/api/v1/rider/documents",
        headers=headers,
        json={"document_type": "IDENTITY_DOCUMENT", "document_url": "https://example.com/id-again.jpg"},
    )
    assert second.status_code == 409


def test_list_documents_returns_all_of_the_riders_own(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/rider/documents", headers=headers, json={"document_type": "DRIVING_LICENSE", "document_url": "https://example.com/a.jpg"})
    client.post("/api/v1/rider/documents", headers=headers, json={"document_type": "VEHICLE_REGISTRATION", "document_url": "https://example.com/b.jpg"})

    response = client.get("/api/v1/rider/documents", headers=headers)
    assert response.status_code == 200
    types = {doc["document_type"] for doc in response.json()}
    assert types == {"DRIVING_LICENSE", "VEHICLE_REGISTRATION"}


def test_replace_a_document_resets_it_to_pending(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    admin_token = _make_admin(client)

    created = client.post(
        "/api/v1/rider/documents", headers=headers,
        json={"document_type": "BANK_DOCUMENT", "document_url": "https://example.com/bank-old.jpg"},
    ).json()

    # Get it rejected first, so replacing it has something meaningful to reset.
    client.patch(
        f"/api/v1/admin/riders/{_rider_id(client, token)}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "REJECTED", "rejection_reason": "Blurry photo"},
    )

    replaced = client.patch(
        f"/api/v1/rider/documents/{created['id']}", headers=headers,
        json={"document_url": "https://example.com/bank-new.jpg"},
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["document_url"] == "https://example.com/bank-new.jpg"
    assert body["verification_status"] == "PENDING"
    assert body["rejection_reason"] is None


def test_delete_a_document(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/rider/documents", headers=headers,
        json={"document_type": "PROFILE_PHOTO", "document_url": "https://example.com/photo.jpg"},
    ).json()

    delete_response = client.delete(f"/api/v1/rider/documents/{created['id']}", headers=headers)
    assert delete_response.status_code == 204

    list_response = client.get("/api/v1/rider/documents", headers=headers)
    assert list_response.json() == []

    # Deleting it again is now a 404, not a repeatable no-op.
    assert client.delete(f"/api/v1/rider/documents/{created['id']}", headers=headers).status_code == 404


def test_deleting_frees_up_the_document_type_for_a_fresh_upload(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"document_type": "IDENTITY_DOCUMENT", "document_url": "https://example.com/id.jpg"}
    created = client.post("/api/v1/rider/documents", headers=headers, json=payload).json()
    client.delete(f"/api/v1/rider/documents/{created['id']}", headers=headers)

    recreated = client.post("/api/v1/rider/documents", headers=headers, json=payload)
    assert recreated.status_code == 201


# --------------------------- Isolation between riders ---------------------------


def test_rider_cannot_see_update_or_delete_another_riders_document(client):
    token_a = _register_and_login_rider(client, email="rider-a-docs@example.com", phone="9300000011")
    token_b = _register_and_login_rider(client, email="rider-b-docs@example.com", phone="9300000012")

    doc_b = client.post(
        "/api/v1/rider/documents", headers={"Authorization": f"Bearer {token_b}"},
        json={"document_type": "DRIVING_LICENSE", "document_url": "https://example.com/b-license.jpg"},
    ).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert client.get("/api/v1/rider/documents", headers=headers_a).json() == []
    assert client.patch(
        f"/api/v1/rider/documents/{doc_b['id']}", headers=headers_a, json={"document_url": "https://example.com/hijacked.jpg"}
    ).status_code == 404
    assert client.delete(f"/api/v1/rider/documents/{doc_b['id']}", headers=headers_a).status_code == 404


def test_customer_and_restaurant_owner_cannot_access_rider_documents(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-docs@example.com", phone="9300000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-docs@example.com", phone="9300000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/documents", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/documents", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/documents").status_code == 401
    assert client.post("/api/v1/rider/documents", json={"document_type": "PROFILE_PHOTO", "document_url": "https://example.com/x.jpg"}).status_code == 401


# --------------------------- Admin review ---------------------------


def test_admin_can_approve_a_document(client):
    token = _register_and_login_rider(client, email="approve-doc@example.com", phone="9300000020")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/rider/documents", headers=headers,
        json={"document_type": "VEHICLE_REGISTRATION", "document_url": "https://example.com/reg.jpg"},
    ).json()
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-docs@example.com", phone="9300000098")

    response = client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "APPROVED"},
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "APPROVED"

    rider_view = client.get("/api/v1/rider/documents", headers=headers).json()
    assert rider_view[0]["verification_status"] == "APPROVED"


def test_admin_rejecting_a_document_requires_a_reason(client):
    token = _register_and_login_rider(client, email="reject-doc@example.com", phone="9300000021")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/rider/documents", headers=headers,
        json={"document_type": "IDENTITY_DOCUMENT", "document_url": "https://example.com/id.jpg"},
    ).json()
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-docs@example.com", phone="9300000097")

    missing_reason = client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "REJECTED"},
    )
    assert missing_reason.status_code == 422

    with_reason = client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "REJECTED", "rejection_reason": "Expired license"},
    )
    assert with_reason.status_code == 200
    assert with_reason.json()["rejection_reason"] == "Expired license"


def test_non_admin_cannot_review_documents(client):
    token = _register_and_login_rider(client, email="target-doc@example.com", phone="9300000022")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/rider/documents", headers=headers,
        json={"document_type": "PROFILE_PHOTO", "document_url": "https://example.com/photo.jpg"},
    ).json()
    rider_id = _rider_id(client, token)
    other_rider_token = _register_and_login_rider(client, email="not-admin-doc@example.com", phone="9300000023")

    response = client.patch(
        f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
        headers={"Authorization": f"Bearer {other_rider_token}"},
        json={"verification_status": "APPROVED"},
    )
    assert response.status_code == 403


def test_admin_document_review_404s_for_document_belonging_to_a_different_rider(client):
    token_a = _register_and_login_rider(client, email="rider-a2-docs@example.com", phone="9300000030")
    token_b = _register_and_login_rider(client, email="rider-b2-docs@example.com", phone="9300000031")
    doc_b = client.post(
        "/api/v1/rider/documents", headers={"Authorization": f"Bearer {token_b}"},
        json={"document_type": "DRIVING_LICENSE", "document_url": "https://example.com/b.jpg"},
    ).json()
    rider_a_id = _rider_id(client, token_a)
    admin_token = _make_admin(client, email="admin4-docs@example.com", phone="9300000096")

    response = client.patch(
        f"/api/v1/admin/riders/{rider_a_id}/documents/{doc_b['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verification_status": "APPROVED"},
    )
    assert response.status_code == 404


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]
