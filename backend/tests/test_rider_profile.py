"""Rider Portal — Phase 2: Rider Profile."""

from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-profile@example.com", phone="9100000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def test_get_profile_returns_the_riders_own_info(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ravi Kumar"
    assert body["email"] == "rider-profile@example.com"
    assert body["phone"] == "9100000010"
    assert body["role"] == "RIDER"
    assert "password_hash" not in response.text


def test_patch_profile_updates_editable_fields(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Ravi K. Sharma",
            "phone": "9100000099",
            "email": "ravi.updated@example.com",
            "profile_image": "https://example.com/avatar.jpg",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ravi K. Sharma"
    assert body["phone"] == "9100000099"
    assert body["email"] == "ravi.updated@example.com"
    assert body["profile_image"] == "https://example.com/avatar.jpg"


def test_patch_profile_partial_update_leaves_other_fields_untouched(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Just A Name Change"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Just A Name Change"
    assert body["email"] == "rider-profile@example.com"
    assert body["phone"] == "9100000010"


def test_patch_profile_rejects_email_already_used_by_another_account(client):
    _register_and_login_rider(client, email="taken@example.com", phone="9100000011", name="Someone Else")
    token = _register_and_login_rider(client, email="me@example.com", phone="9100000012", name="Me")

    response = client.patch(
        "/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"}, json={"email": "taken@example.com"}
    )
    assert response.status_code == 409

    # The rider's own email is untouched after the rejected attempt.
    profile = client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"})
    assert profile.json()["email"] == "me@example.com"


def test_patch_profile_rejects_phone_already_used_by_another_account(client):
    _register_and_login_rider(client, email="phone-taken@example.com", phone="9100000021", name="Someone Else")
    token = _register_and_login_rider(client, email="phone-me@example.com", phone="9100000022", name="Me")

    response = client.patch(
        "/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"}, json={"phone": "9100000021"}
    )
    assert response.status_code == 409


def test_patch_profile_allows_keeping_own_current_email_and_phone(client):
    """Re-submitting the rider's own current email/phone (e.g. a form that
    always sends every field) must not falsely trigger the duplicate check
    against themselves."""
    token = _register_and_login_rider(client, email="self@example.com", phone="9100000030", name="Self")
    response = client.patch(
        "/api/v1/rider/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "self@example.com", "phone": "9100000030", "name": "Self Updated"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Self Updated"


def test_only_the_authenticated_rider_can_see_their_own_profile_not_someone_elses(client):
    """There's no /profile/{id} route at all — a rider can only ever reach
    their own record, scoped implicitly by their own access token."""
    token_a = _register_and_login_rider(client, email="ridera@example.com", phone="9100000041", name="Rider A")
    _register_and_login_rider(client, email="riderb@example.com", phone="9100000042", name="Rider B")

    response = client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token_a}"})
    assert response.status_code == 200
    assert response.json()["name"] == "Rider A"


def test_customer_and_restaurant_owner_cannot_access_rider_profile(client):
    from app.core.security import create_access_token, hash_password
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c@example.com", phone="9100000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o@example.com", phone="9100000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_to_rider_profile_is_rejected(client):
    assert client.get("/api/v1/rider/profile").status_code == 401
    assert client.patch("/api/v1/rider/profile", json={"name": "x"}).status_code == 401


def test_invalid_email_format_is_rejected(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"}, json={"email": "not-an-email"}
    )
    assert response.status_code == 422


def test_blank_name_is_rejected(client):
    token = _register_and_login_rider(client)
    response = client.patch("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token}"}, json={"name": "A"})
    assert response.status_code == 422
