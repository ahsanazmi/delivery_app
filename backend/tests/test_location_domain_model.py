"""Maps & Location System Phase 2 — Location Domain Model.

Covers the three fields this phase adds to the existing Address model
(district, formatted_address, place_id) — additive, all nullable, so
every existing address-creation path continues to work unchanged
(already re-confirmed by the full existing suite passing with no
changes needed there). This file's own job is just proving the three
new fields themselves round-trip correctly and stay optional.
"""

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole


def _customer_token(client, email="location-p2@example.com", phone="9700000099") -> str:
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = User(name="Customer", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return token


def test_address_accepts_and_returns_the_new_location_fields(client):
    headers = {"Authorization": f"Bearer {_customer_token(client)}"}
    response = client.post(
        "/api/v1/addresses", headers=headers,
        json={
            "recipient_name": "Ravi", "phone": "9999999999", "address_line": "1 Road",
            "city": "Azamgarh", "district": "Azamgarh", "state": "Uttar Pradesh", "postal_code": "276001",
            "latitude": "26.0680000", "longitude": "83.1836000",
            "formatted_address": "1 Road, Azamgarh, Uttar Pradesh 276001, India",
            "place_id": "ChIJ_test_place_id_azamgarh",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["district"] == "Azamgarh"
    assert body["formatted_address"] == "1 Road, Azamgarh, Uttar Pradesh 276001, India"
    assert body["place_id"] == "ChIJ_test_place_id_azamgarh"

    fetched = client.get(f"/api/v1/addresses/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["district"] == "Azamgarh"


def test_address_new_location_fields_stay_optional(client):
    """Manual address entry, with no map/search interaction at all, must
    keep working exactly as before this phase — every new field is
    nullable and absent-by-default."""
    headers = {"Authorization": f"Bearer {_customer_token(client, email='location-p2b@example.com', phone='9700000098')}"}
    response = client.post(
        "/api/v1/addresses", headers=headers,
        json={"recipient_name": "Priya", "phone": "9888888888", "address_line": "2 Lane", "city": "Town", "state": "ST", "postal_code": "123456"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["district"] is None
    assert body["formatted_address"] is None
    assert body["place_id"] is None


def test_address_district_and_place_id_are_updatable_via_patch(client):
    headers = {"Authorization": f"Bearer {_customer_token(client, email='location-p2c@example.com', phone='9700000097')}"}
    created = client.post(
        "/api/v1/addresses", headers=headers,
        json={"recipient_name": "Amit", "phone": "9777777777", "address_line": "3 Street", "city": "Town", "state": "ST", "postal_code": "123456"},
    ).json()

    patched = client.patch(
        f"/api/v1/addresses/{created['id']}", headers=headers,
        json={"district": "Jaunpur", "place_id": "ChIJ_updated_place_id"},
    )
    assert patched.status_code == 200
    assert patched.json()["district"] == "Jaunpur"
    assert patched.json()["place_id"] == "ChIJ_updated_place_id"
    # Untouched fields survive the partial update unchanged.
    assert patched.json()["city"] == "Town"


def test_customer_a_cannot_read_customer_bs_address_with_the_new_fields(client):
    """Re-confirms existing IDOR protection still holds after the model
    change — a plain regression guard, not new authorization logic."""
    token_a = _customer_token(client, email="location-p2d-a@example.com", phone="9700000096")
    token_b = _customer_token(client, email="location-p2d-b@example.com", phone="9700000095")

    created = client.post(
        "/api/v1/addresses", headers={"Authorization": f"Bearer {token_a}"},
        json={"recipient_name": "Aisha", "phone": "9666666666", "address_line": "4 Road", "city": "Town", "state": "ST", "postal_code": "123456", "district": "Secret District"},
    ).json()

    response = client.get(f"/api/v1/addresses/{created['id']}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404
