"""Admin Portal — Phase 15: Platform Categories.

The global, home-page-browsing Category model (app/models/category.py) is
distinct from MenuCategory (restaurant-scoped menu sections) — this admin
module must only ever touch Category, never MenuCategory. Several tests
here directly prove that boundary.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.category import Category
from app.models.product import MenuCategory
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

CATEGORIES_URL = "/api/v1/admin/categories"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p15-{uuid.uuid4().hex[:8]}@example.com", phone=f"81{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_category(db, *, name, is_active=True, display_order=0):
    category = Category(name=name, is_active=is_active, display_order=display_order)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def _make_restaurant(db, *, category_id=None):
    owner = _make_user(db, name="Owner", email=f"owner-p15-{uuid.uuid4().hex[:8]}@example.com", phone=f"80{uuid.uuid4().hex[:8]}", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, category_id=category_id, name="Some Restaurant", phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p15@example.com", phone="8000000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(CATEGORIES_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(CATEGORIES_URL).status_code == 401


def test_list_includes_inactive_categories_unlike_customer_endpoint(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_category(db, name="Active Cat P15", is_active=True)
    _make_category(db, name="Inactive Cat P15", is_active=False)

    response = client.get(CATEGORIES_URL, headers=headers)
    names = [item["name"] for item in response.json()["items"]]
    assert "Active Cat P15" in names
    assert "Inactive Cat P15" in names


def test_list_includes_restaurant_count(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    category = _make_category(db, name="Counted Cat P15")
    _make_restaurant(db, category_id=category.id)
    _make_restaurant(db, category_id=category.id)

    response = client.get(CATEGORIES_URL, headers=headers)
    match = next(item for item in response.json()["items"] if item["id"] == str(category.id))
    assert match["restaurant_count"] == 2


def test_create_category(client):
    db = _db(client)
    _, headers = _admin_headers(db)

    response = client.post(CATEGORIES_URL, headers=headers, json={"name": "Brand New Cat P15", "display_order": 5})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Brand New Cat P15"
    assert body["is_active"] is True
    assert body["restaurant_count"] == 0


def test_create_duplicate_name_is_conflict(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_category(db, name="Duplicate Cat P15")

    response = client.post(CATEGORIES_URL, headers=headers, json={"name": "Duplicate Cat P15"})
    assert response.status_code == 409


def test_update_category(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    category = _make_category(db, name="To Update P15")

    response = client.patch(f"{CATEGORIES_URL}/{category.id}", headers=headers, json={"display_order": 9, "is_active": False})
    assert response.status_code == 200
    body = response.json()
    assert body["display_order"] == 9
    assert body["is_active"] is False


def test_update_requires_at_least_one_field(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    category = _make_category(db, name="Empty Update P15")

    response = client.patch(f"{CATEGORIES_URL}/{category.id}", headers=headers, json={})
    assert response.status_code == 422


def test_update_to_duplicate_name_is_conflict(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_category(db, name="Taken Name P15")
    other = _make_category(db, name="Other Name P15")

    response = client.patch(f"{CATEGORIES_URL}/{other.id}", headers=headers, json={"name": "Taken Name P15"})
    assert response.status_code == 409


def test_update_404_for_missing_category(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    response = client.patch(f"{CATEGORIES_URL}/00000000-0000-0000-0000-000000000000", headers=headers, json={"display_order": 1})
    assert response.status_code == 404


def test_delete_category_with_no_restaurants(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    category = _make_category(db, name="Deletable Cat P15")

    response = client.delete(f"{CATEGORIES_URL}/{category.id}", headers=headers)
    assert response.status_code == 204
    assert db.query(Category).filter(Category.id == category.id).count() == 0


def test_delete_blocked_when_restaurants_reference_it(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    category = _make_category(db, name="In Use Cat P15")
    _make_restaurant(db, category_id=category.id)

    response = client.delete(f"{CATEGORIES_URL}/{category.id}", headers=headers)
    assert response.status_code == 409
    assert db.get(Category, category.id) is not None


def test_delete_404_for_missing_category(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    response = client.delete(f"{CATEGORIES_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_admin_category_actions_never_touch_menu_category(client):
    """The core safety requirement of this phase: admin platform-category
    CRUD must never read, write, or otherwise affect restaurant-scoped
    MenuCategory rows."""
    db = _db(client)
    _, headers = _admin_headers(db)
    restaurant = _make_restaurant(db)
    menu_category = MenuCategory(restaurant_id=restaurant.id, name="Starters", display_order=0)
    db.add(menu_category)
    db.commit()
    db.refresh(menu_category)

    # Create, update, and delete platform categories freely...
    created = client.post(CATEGORIES_URL, headers=headers, json={"name": "Isolated Platform Cat P15"}).json()
    client.patch(f"{CATEGORIES_URL}/{created['id']}", headers=headers, json={"display_order": 3})
    client.delete(f"{CATEGORIES_URL}/{created['id']}", headers=headers)

    # ...and the restaurant's own menu category is completely untouched.
    db.refresh(menu_category)
    assert menu_category.name == "Starters"
    assert menu_category.restaurant_id == restaurant.id
    assert db.query(MenuCategory).filter(MenuCategory.id == menu_category.id).count() == 1


def test_search_by_name(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_category(db, name="Findable Cuisine P15")
    _make_category(db, name="Other Cuisine P15")

    response = client.get(CATEGORIES_URL, headers=headers, params={"search": "Findable"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Findable Cuisine P15"]


def test_is_active_filter(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_category(db, name="Active Filter P15", is_active=True)
    _make_category(db, name="Inactive Filter P15", is_active=False)

    response = client.get(CATEGORIES_URL, headers=headers, params={"is_active": "false"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Inactive Filter P15"]
