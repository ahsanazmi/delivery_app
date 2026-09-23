"""Rider Portal — Phase 5: Vehicle Information."""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-vehicle@example.com", phone="9400000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def test_new_rider_has_no_vehicle_info_yet(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_type"] is None
    assert body["vehicle_number"] is None
    assert body["vehicle_model"] is None


def test_patch_sets_all_vehicle_fields(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/vehicle",
        headers={"Authorization": f"Bearer {token}"},
        json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234", "vehicle_model": "Honda Activa"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_type"] == "BIKE"
    assert body["vehicle_number"] == "KA01AB1234"
    assert body["vehicle_model"] == "Honda Activa"


def test_patch_is_partial_and_leaves_other_fields_untouched(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    client.patch("/api/v1/rider/vehicle", headers=headers, json={"vehicle_type": "SCOOTER", "vehicle_number": "KA05CD5678"})

    response = client.patch("/api/v1/rider/vehicle", headers=headers, json={"vehicle_model": "TVS Jupiter"})
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_type"] == "SCOOTER"
    assert body["vehicle_number"] == "KA05CD5678"
    assert body["vehicle_model"] == "TVS Jupiter"


def test_every_vehicle_type_is_accepted(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    for vehicle_type in ("BIKE", "SCOOTER", "BICYCLE", "OTHER"):
        response = client.patch("/api/v1/rider/vehicle", headers=headers, json={"vehicle_type": vehicle_type})
        assert response.status_code == 200
        assert response.json()["vehicle_type"] == vehicle_type


def test_invalid_vehicle_type_is_rejected(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {token}"}, json={"vehicle_type": "CAR"}
    )
    assert response.status_code == 422


def test_blank_vehicle_number_is_rejected(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {token}"}, json={"vehicle_number": ""}
    )
    assert response.status_code == 422


def test_only_the_authenticated_rider_sees_their_own_vehicle_info(client):
    token_a = _register_and_login_rider(client, email="rider-a-vehicle@example.com", phone="9400000011")
    token_b = _register_and_login_rider(client, email="rider-b-vehicle@example.com", phone="9400000012")

    client.patch(
        "/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {token_b}"},
        json={"vehicle_type": "BIKE", "vehicle_number": "KA01ZZ9999"},
    )

    response_a = client.get("/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {token_a}"})
    assert response_a.json()["vehicle_number"] is None  # A's own (empty) record, not B's


def test_customer_and_restaurant_owner_cannot_access_rider_vehicle(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-vehicle@example.com", phone="9400000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-vehicle@example.com", phone="9400000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/vehicle", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/vehicle").status_code == 401
    assert client.patch("/api/v1/rider/vehicle", json={"vehicle_type": "BIKE"}).status_code == 401
