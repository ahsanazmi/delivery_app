"""Admin Portal — Phase 16: Service Areas.

Two halves: admin CRUD over ServiceArea/ServiceAreaPostalCode (using the
shared `client` fixture, matching every other admin_*.py test file), and a
real end-to-end proof that customer order placement actually respects
service-area configuration (using a dedicated engine + real HTTP calls,
matching the established customer<->restaurant integration test pattern).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.services.addresses import create_address

SERVICE_AREAS_URL = "/api/v1/admin/service-areas"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p16@example.com", phone="8100000001", role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p16@example.com", phone="8100000010", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(SERVICE_AREAS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(SERVICE_AREAS_URL).status_code == 401


def test_create_and_list_service_area(client):
    db = _db(client)
    headers = _admin_headers(db)

    create = client.post(
        SERVICE_AREAS_URL, headers=headers,
        json={"city": "Bengaluru", "district": "Bengaluru Urban", "zone_name": "Koramangala", "postal_codes": ["560034", "560095"]},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["city"] == "Bengaluru"
    assert sorted(body["postal_codes"]) == ["560034", "560095"]
    assert body["is_active"] is True

    listing = client.get(SERVICE_AREAS_URL, headers=headers)
    names = [item["zone_name"] for item in listing.json()["items"]]
    assert "Koramangala" in names


def test_create_deduplicates_postal_codes(client):
    db = _db(client)
    headers = _admin_headers(db)

    create = client.post(
        SERVICE_AREAS_URL, headers=headers,
        json={"city": "Mumbai", "zone_name": "Andheri", "postal_codes": ["400053", "400053", " 400053 "]},
    )
    assert create.status_code == 201
    assert create.json()["postal_codes"] == ["400053"]


def test_create_rejects_postal_code_already_used_by_another_zone(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Delhi", "zone_name": "Zone A", "postal_codes": ["110001"]})

    conflict = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Delhi", "zone_name": "Zone B", "postal_codes": ["110001"]})
    assert conflict.status_code == 409


def test_create_requires_at_least_one_postal_code(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Pune", "zone_name": "Empty Zone", "postal_codes": []})
    assert response.status_code == 422


def test_update_renames_and_replaces_postal_codes(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Chennai", "zone_name": "Old Name", "postal_codes": ["600001"]})
    area_id = create.json()["id"]

    update = client.patch(
        f"{SERVICE_AREAS_URL}/{area_id}", headers=headers,
        json={"zone_name": "New Name", "postal_codes": ["600002", "600003"]},
    )
    assert update.status_code == 200
    body = update.json()
    assert body["zone_name"] == "New Name"
    assert sorted(body["postal_codes"]) == ["600002", "600003"]


def test_update_can_deactivate_without_touching_postal_codes(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Hyderabad", "zone_name": "Zone X", "postal_codes": ["500001"]})
    area_id = create.json()["id"]

    update = client.patch(f"{SERVICE_AREAS_URL}/{area_id}", headers=headers, json={"is_active": False})
    assert update.status_code == 200
    body = update.json()
    assert body["is_active"] is False
    assert body["postal_codes"] == ["500001"]


def test_update_rejects_postal_code_conflict_with_another_zone(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Kolkata", "zone_name": "Zone One", "postal_codes": ["700001"]})
    create_two = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Kolkata", "zone_name": "Zone Two", "postal_codes": ["700002"]})
    area_two_id = create_two.json()["id"]

    conflict = client.patch(f"{SERVICE_AREAS_URL}/{area_two_id}", headers=headers, json={"postal_codes": ["700001"]})
    assert conflict.status_code == 409


def test_update_requires_at_least_one_field(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Jaipur", "zone_name": "Zone", "postal_codes": ["302001"]})
    area_id = create.json()["id"]

    response = client.patch(f"{SERVICE_AREAS_URL}/{area_id}", headers=headers, json={})
    assert response.status_code == 422


def test_update_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(f"{SERVICE_AREAS_URL}/00000000-0000-0000-0000-000000000000", headers=headers, json={"is_active": False})
    assert response.status_code == 404


def test_delete_service_area(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Lucknow", "zone_name": "Zone", "postal_codes": ["226001"]})
    area_id = create.json()["id"]

    response = client.delete(f"{SERVICE_AREAS_URL}/{area_id}", headers=headers)
    assert response.status_code == 204

    listing = client.get(SERVICE_AREAS_URL, headers=headers, params={"search": "Lucknow"})
    assert listing.json()["items"] == []


def test_delete_frees_up_postal_code_for_reuse(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Nagpur", "zone_name": "Zone", "postal_codes": ["440001"]})
    area_id = create.json()["id"]
    client.delete(f"{SERVICE_AREAS_URL}/{area_id}", headers=headers)

    reuse = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Nagpur", "zone_name": "New Zone", "postal_codes": ["440001"]})
    assert reuse.status_code == 201


def test_delete_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.delete(f"{SERVICE_AREAS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_search_and_active_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Findable City", "zone_name": "Zone", "postal_codes": ["999001"]})
    inactive = client.post(SERVICE_AREAS_URL, headers=headers, json={"city": "Other City", "zone_name": "Inactive Zone", "postal_codes": ["999002"]})
    client.patch(f"{SERVICE_AREAS_URL}/{inactive.json()['id']}", headers=headers, json={"is_active": False})

    by_search = client.get(SERVICE_AREAS_URL, headers=headers, params={"search": "Findable"})
    assert [i["city"] for i in by_search.json()["items"]] == ["Findable City"]

    by_active = client.get(SERVICE_AREAS_URL, headers=headers, params={"is_active": "false"})
    cities = [i["city"] for i in by_active.json()["items"]]
    assert "Other City" in cities
    assert "Findable City" not in cities


# --------------------------- Checkout integration ---------------------------


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _seed_order_placement_scenario(seed, *, postal_code):
    owner = User(name="Owner", email="owner-p16@example.com", phone="8100000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Cust P16", email="cust-p16@example.com", phone="8100000021", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    seed.add_all([owner, customer])
    seed.commit()

    restaurant = Restaurant(
        owner_id=owner.id, name="Diner P16", phone="9876500001", address="Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    seed.add(restaurant)
    seed.commit()

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    seed.add(product)
    seed.commit()

    address = create_address(seed, customer.id, {
        "label": "Home", "recipient_name": "Cust P16", "phone": "8100000021",
        "address_line": "1 Road", "city": "Testville", "state": "TS", "postal_code": postal_code,
    })

    return {
        "customer_token": create_access_token(customer.id),
        "product_id": str(product.id),
        "address_id": str(address.id),
    }


def _place_order(client, scenario):
    client.post("/api/v1/customer/cart/items", headers={"Authorization": f"Bearer {scenario['customer_token']}"}, json={"product_id": scenario["product_id"], "quantity": 1})
    return client.post(
        "/api/v1/customer/orders",
        headers={"Authorization": f"Bearer {scenario['customer_token']}"},
        json={"address_id": scenario["address_id"]},
    )


def _admin_headers_for_engine(engine):
    with Session(engine) as db:
        admin = User(name="Admin P16", email="admin-checkout-p16@example.com", phone="8100000030", password_hash=hash_password("x"), role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_order_placement_succeeds_when_no_service_areas_configured(engine):
    """Fail-open: a brand-new, unconfigured feature must never block every
    existing order in the platform."""
    with Session(engine) as seed:
        scenario = _seed_order_placement_scenario(seed, postal_code="999999")

    with TestClient(app) as client:
        response = _place_order(client, scenario)
        assert response.status_code == 201


def test_order_placement_blocked_for_uncovered_postal_code(engine):
    with Session(engine) as seed:
        scenario = _seed_order_placement_scenario(seed, postal_code="111111")

    admin_headers = _admin_headers_for_engine(engine)
    with TestClient(app) as client:
        client.post(
            "/api/v1/admin/service-areas", headers=admin_headers,
            json={"city": "Covered City", "zone_name": "Zone", "postal_codes": ["222222"]},
        )
        response = _place_order(client, scenario)
        assert response.status_code == 422


def test_order_placement_succeeds_for_covered_and_active_postal_code(engine):
    with Session(engine) as seed:
        scenario = _seed_order_placement_scenario(seed, postal_code="333333")

    admin_headers = _admin_headers_for_engine(engine)
    with TestClient(app) as client:
        client.post(
            "/api/v1/admin/service-areas", headers=admin_headers,
            json={"city": "Covered City", "zone_name": "Zone", "postal_codes": ["333333"]},
        )
        response = _place_order(client, scenario)
        assert response.status_code == 201


def test_order_placement_blocked_when_covering_zone_is_inactive(engine):
    with Session(engine) as seed:
        scenario = _seed_order_placement_scenario(seed, postal_code="444444")

    admin_headers = _admin_headers_for_engine(engine)
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/admin/service-areas", headers=admin_headers,
            json={"city": "Covered City", "zone_name": "Zone", "postal_codes": ["444444"]},
        )
        client.patch(f"/api/v1/admin/service-areas/{create.json()['id']}", headers=admin_headers, json={"is_active": False})

        response = _place_order(client, scenario)
        assert response.status_code == 422


def test_checkout_preview_warns_about_unserviceable_address(engine):
    with Session(engine) as seed:
        scenario = _seed_order_placement_scenario(seed, postal_code="555555")

    admin_headers = _admin_headers_for_engine(engine)
    with TestClient(app) as client:
        client.post(
            "/api/v1/admin/service-areas", headers=admin_headers,
            json={"city": "Covered City", "zone_name": "Zone", "postal_codes": ["666666"]},
        )
        client.post("/api/v1/customer/cart/items", headers={"Authorization": f"Bearer {scenario['customer_token']}"}, json={"product_id": scenario["product_id"], "quantity": 1})
        preview = client.get("/api/v1/customer/checkout", headers={"Authorization": f"Bearer {scenario['customer_token']}"})
        assert preview.status_code == 200
        assert any("deliver" in issue.lower() for issue in preview.json()["issues"])
