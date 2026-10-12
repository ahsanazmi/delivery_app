"""E2E Validation Phase 9 — address defaults and coordinate-pair defects
found during live testing against PostgreSQL."""

from tests.test_address_crud_and_delivery_fee import _customer_token

ADDRESS = {"recipient_name": "Customer", "phone": "9999999999", "city": "Lucknow", "state": "Uttar Pradesh", "postal_code": "226001"}


def _create(client, headers, line, **extra):
    response = client.post("/api/v1/addresses", headers=headers, json={**ADDRESS, "address_line": line, **extra})
    assert response.status_code == 201
    return response.json()


def test_a_customers_first_address_becomes_default_when_is_default_is_omitted(client):
    headers = {"Authorization": f"Bearer {_customer_token(client, 'first-default@example.com', '9700000101')}"}
    first = _create(client, headers, "1 First Street")
    second = _create(client, headers, "2 Second Street")
    assert first["is_default"] is True
    assert second["is_default"] is False


def test_an_explicit_is_default_false_on_the_first_address_is_respected(client):
    headers = {"Authorization": f"Bearer {_customer_token(client, 'explicit-false@example.com', '9700000102')}"}
    assert _create(client, headers, "1 First Street", is_default=False)["is_default"] is False


def test_deleting_the_default_address_promotes_a_remaining_one(client):
    headers = {"Authorization": f"Bearer {_customer_token(client, 'promote@example.com', '9700000103')}"}
    first = _create(client, headers, "1 First Street")
    second = _create(client, headers, "2 Second Street")
    assert client.patch(f"/api/v1/addresses/{second['id']}/default", headers=headers).status_code == 200

    assert client.delete(f"/api/v1/addresses/{second['id']}", headers=headers).status_code == 200

    remaining = client.get("/api/v1/addresses", headers=headers).json()
    assert [(a["id"], a["is_default"]) for a in remaining] == [(first["id"], True)]


def test_patching_only_one_coordinate_to_null_is_rejected(client):
    headers = {"Authorization": f"Bearer {_customer_token(client, 'half-pin@example.com', '9700000104')}"}
    address = _create(client, headers, "1 Pinned Street", latitude="26.8505899", longitude="80.9499875")

    assert client.patch(f"/api/v1/addresses/{address['id']}", headers=headers, json={"latitude": None}).status_code == 422
    unchanged = client.get(f"/api/v1/addresses/{address['id']}", headers=headers).json()
    assert unchanged["latitude"] is not None and unchanged["longitude"] is not None

    cleared = client.patch(f"/api/v1/addresses/{address['id']}", headers=headers, json={"latitude": None, "longitude": None})
    assert cleared.status_code == 200
    assert cleared.json()["latitude"] is None and cleared.json()["longitude"] is None
