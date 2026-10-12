"""Delivery radius — customers only see restaurants whose radius (their own,
or the platform default of 5 km) covers their location, nearest first, and
checkout blocks addresses outside that radius.

~0.009° of latitude is ~1 km, so distances below are approximate."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models import Address, Product
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services import checkout as checkout_service
from app.services.cart import add_item, create_cart_for_user

LIST_URL = "/api/v1/customer/restaurants"
BASE_LAT = Decimal("26.0486")
BASE_LNG = Decimal("82.6847")


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _user(db, email, role):
    user = User(name="User", email=email, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, name, km_north, radius=None, approval_status=ApprovalStatus.APPROVED):
    owner = _user(db, f"{name.lower().replace(' ', '')}@example.com", UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876500000", address="Addr",
        latitude=BASE_LAT + Decimal("0.009") * Decimal(str(km_north)), longitude=BASE_LNG,
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
        delivery_radius_km=radius, approval_status=approval_status,
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _here(km_north=0):
    return {"latitude": str(BASE_LAT + Decimal("0.009") * Decimal(str(km_north))), "longitude": str(BASE_LNG)}


def _admin_headers(db):
    admin = _user(db, "admin-radius@example.com", UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_lists_only_restaurants_within_default_radius_nearest_first(client):
    db = _db(client)
    _restaurant(db, "Far Dhaba", km_north=8)
    _restaurant(db, "Mid Cafe", km_north=3)
    _restaurant(db, "Near Chai", km_north=1)

    response = client.get(LIST_URL, params=_here())
    assert response.status_code == 200
    body = response.json()
    assert [r["name"] for r in body] == ["Near Chai", "Mid Cafe"]
    assert 0.9 < body[0]["distance_km"] < 1.1


def test_per_restaurant_radius_overrides_default(client):
    db = _db(client)
    _restaurant(db, "Big Range Dhaba", km_north=8, radius=Decimal("10"))
    _restaurant(db, "Tiny Stall", km_north=3, radius=Decimal("2"))

    names = [r["name"] for r in client.get(LIST_URL, params=_here()).json()]
    assert names == ["Big Range Dhaba"]


def test_admin_changes_default_radius(client):
    db = _db(client)
    headers = _admin_headers(db)
    _restaurant(db, "Mid Cafe", km_north=3)
    assert len(client.get(LIST_URL, params=_here()).json()) == 1

    update = client.patch("/api/v1/admin/settings", headers=headers, json={"default_delivery_radius_km": "2"})
    assert update.status_code == 200, update.text
    assert Decimal(update.json()["default_delivery_radius_km"]) == Decimal("2")
    assert client.get(LIST_URL, params=_here()).json() == []


def test_admin_sets_and_clears_restaurant_radius(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _restaurant(db, "Far Dhaba", km_north=8)
    url = f"/api/v1/admin/restaurants/{restaurant.id}/delivery-radius"

    set_resp = client.patch(url, headers=headers, json={"delivery_radius_km": "9", "reason": "Own delivery staff"})
    assert set_resp.status_code == 200, set_resp.text
    assert Decimal(set_resp.json()["effective_delivery_radius_km"]) == Decimal("9")
    assert [r["name"] for r in client.get(LIST_URL, params=_here()).json()] == ["Far Dhaba"]

    clear = client.patch(url, headers=headers, json={"delivery_radius_km": None, "reason": "Back to default"})
    assert clear.json()["delivery_radius_km"] is None
    assert Decimal(clear.json()["effective_delivery_radius_km"]) == Decimal("5")
    assert client.get(LIST_URL, params=_here()).json() == []

    assert client.patch(url, headers=headers, json={"delivery_radius_km": "0", "reason": "x"}).status_code == 422


def test_pending_restaurants_never_listed_even_when_near(client):
    db = _db(client)
    _restaurant(db, "Pending Place", km_north=0.5, approval_status=ApprovalStatus.PENDING)
    assert client.get(LIST_URL, params=_here()).json() == []


def test_without_location_returns_full_list_and_half_location_is_rejected(client):
    db = _db(client)
    _restaurant(db, "Far Dhaba", km_north=8)
    _restaurant(db, "Near Chai", km_north=1)
    body = client.get(LIST_URL).json()
    assert len(body) == 2
    assert all(r["distance_km"] is None for r in body)
    assert client.get(LIST_URL, params={"latitude": "26.0"}).status_code == 422


def test_search_limits_restaurants_and_dishes_to_nearby(client):
    db = _db(client)
    near = _restaurant(db, "Near Chai", km_north=1)
    far = _restaurant(db, "Far Chai", km_north=8)
    db.add_all([
        Product(restaurant_id=near.id, name="Masala Chai", price=Decimal("20")),
        Product(restaurant_id=far.id, name="Masala Chai Special", price=Decimal("25")),
    ])
    db.commit()

    body = client.get("/api/v1/customer/search", params={"q": "chai", **_here()}).json()
    assert [r["name"] for r in body["restaurants"]] == ["Near Chai"]
    assert [p["name"] for p in body["products"]] == ["Masala Chai"]


def test_checkout_blocks_address_outside_radius(client):
    db = _db(client)
    restaurant = _restaurant(db, "Mid Cafe", km_north=3)
    customer = _user(db, "cust-radius@example.com", UserRole.CUSTOMER)
    product = Product(restaurant_id=restaurant.id, name="Tea", price=Decimal("40"))
    db.add(product)
    db.commit()
    add_item(db, create_cart_for_user(db, customer.id), product.id, 1)
    address = Address(
        user_id=customer.id, label="Home", recipient_name="C", phone="9999999999", address_line="Lane 1",
        city="Shahganj", state="UP", postal_code="223101", is_default=True,
        latitude=BASE_LAT + Decimal("0.009") * 10, longitude=BASE_LNG,
    )
    db.add(address)
    db.commit()

    issues = checkout_service.get_checkout_preview(db, customer)["issues"]
    assert any("delivers within 5 km" in issue for issue in issues), issues

    address.latitude = BASE_LAT + Decimal("0.009") * 2
    db.commit()
    issues = checkout_service.get_checkout_preview(db, customer)["issues"]
    assert not any("delivers within" in issue for issue in issues), issues
