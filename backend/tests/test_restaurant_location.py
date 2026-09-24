"""Maps & Location System Phase 3 — Restaurant Location.

Covers the two fields this phase adds to the existing Restaurant model
(formatted_address, place_id — additive, nullable, mirroring Phase 2's
Address change) plus the genuine gap this phase found: AdminRestaurantDetail
never exposed address/latitude/longitude/formatted_address/place_id at
all, so "admin should be able to inspect the location" wasn't actually
true before this phase. Coordinate validation itself (required, range-
checked lat/lng) already existed and is only re-confirmed here, not
newly built.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _owner_with_restaurant(client, tag: str):
    db = _db(client)
    owner = User(name="Owner", email=f"loc-owner-{tag}@example.com", phone=f"940100{tag}"[:10], password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    token = create_access_token(owner.id)
    restaurant_id = str(restaurant.id)
    db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "restaurant_id": restaurant_id}


def _admin_headers(client, tag: str):
    db = _db(client)
    admin = User(name="Admin", email=f"loc-admin-{tag}@example.com", phone=f"940200{tag}"[:10], password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def test_owner_can_set_and_read_formatted_address_and_place_id(client):
    ctx = _owner_with_restaurant(client, "a")
    response = client.patch(
        "/api/v1/restaurant/profile", headers=ctx["headers"],
        json={"formatted_address": "1 Road, Azamgarh, Uttar Pradesh 276001, India", "place_id": "ChIJ_restaurant_place_id"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["formatted_address"] == "1 Road, Azamgarh, Uttar Pradesh 276001, India"
    assert body["place_id"] == "ChIJ_restaurant_place_id"

    fetched = client.get("/api/v1/restaurant/profile", headers=ctx["headers"])
    assert fetched.json()["place_id"] == "ChIJ_restaurant_place_id"


def test_restaurant_new_location_fields_stay_optional(client):
    """Every existing restaurant, created via manual address/lat/lng entry
    (today's only path), must keep having these two fields simply null —
    never a required-field error."""
    ctx = _owner_with_restaurant(client, "b")
    response = client.get("/api/v1/restaurant/profile", headers=ctx["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["formatted_address"] is None
    assert body["place_id"] is None


def test_impossible_coordinates_are_still_rejected(client):
    """Re-confirms the existing lat/lng range validation still holds after
    the model change — pre-existing behavior, not new this phase."""
    ctx = _owner_with_restaurant(client, "c")
    response = client.patch(
        "/api/v1/restaurant/profile", headers=ctx["headers"],
        json={"latitude": "999.0"},
    )
    assert response.status_code == 422


def test_admin_can_now_inspect_restaurant_location(client):
    """The genuine gap this phase closes: AdminRestaurantDetail previously
    carried no address/coordinates at all."""
    ctx = _owner_with_restaurant(client, "d")
    client.patch(
        "/api/v1/restaurant/profile", headers=ctx["headers"],
        json={"formatted_address": "1 Road, Town", "place_id": "ChIJ_admin_visible"},
    )

    admin_headers = _admin_headers(client, "d")
    detail = client.get(f"/api/v1/admin/restaurants/{ctx['restaurant_id']}", headers=admin_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["address"] == "1 Road"
    assert Decimal(body["latitude"]) == Decimal("12.1")
    assert Decimal(body["longitude"]) == Decimal("77.1")
    assert body["formatted_address"] == "1 Road, Town"
    assert body["place_id"] == "ChIJ_admin_visible"
