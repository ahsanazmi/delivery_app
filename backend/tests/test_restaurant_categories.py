"""Restaurant Owner Portal — Phase 5: restaurant (menu) categories."""

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
from app.models import Restaurant, User, UserRole
from app.models.product import MenuCategory


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com", phone="9000000001"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House"):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _http_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def _teardown(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_create_and_list_categories():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            create_resp = client.post(
                "/api/v1/restaurant/categories",
                headers=headers,
                json={"name": "Pizza", "display_order": 1, "image_url": "https://example.com/pizza.png"},
            )
            assert create_resp.status_code == 201
            body = create_resp.json()
            assert body["name"] == "Pizza"
            assert body["image_url"] == "https://example.com/pizza.png"
            assert body["is_active"] is True

            client.post("/api/v1/restaurant/categories", headers=headers, json={"name": "Burgers", "display_order": 2})

            list_resp = client.get("/api/v1/restaurant/categories", headers=headers)
            assert list_resp.status_code == 200
            names = [c["name"] for c in list_resp.json()]
            assert names == ["Pizza", "Burgers"]
    finally:
        _teardown(engine)


def test_get_single_category():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            category = MenuCategory(restaurant_id=restaurant.id, name="Biryani")
            seed.add(category)
            seed.commit()
            category_id = category.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/categories/{category_id}", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["name"] == "Biryani"
    finally:
        _teardown(engine)


def test_patch_category_renames_and_toggles_active():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            category = MenuCategory(restaurant_id=restaurant.id, name="Chinese")
            seed.add(category)
            seed.commit()
            category_id = category.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = client.patch(
                f"/api/v1/restaurant/categories/{category_id}",
                headers=headers,
                json={"name": "Asian", "is_active": False},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["name"] == "Asian"
            assert body["is_active"] is False
    finally:
        _teardown(engine)


def test_disabled_category_still_listed_for_owner_but_not_customer(db):
    from app.services.products import list_menu_categories, list_menu_categories_for_owner

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    active = MenuCategory(restaurant_id=restaurant.id, name="Drinks", is_active=True)
    disabled = MenuCategory(restaurant_id=restaurant.id, name="Desserts", is_active=False)
    db.add_all([active, disabled])
    db.commit()

    owner_view = {c.name for c in list_menu_categories_for_owner(db, restaurant.id)}
    customer_view = {c.name for c in list_menu_categories(db, restaurant.id)}

    assert owner_view == {"Drinks", "Desserts"}
    assert customer_view == {"Drinks"}


def test_delete_category_removes_it_but_keeps_the_product(db):
    """Deleting a category must never delete the products in it — only the
    category itself goes away. The FK's ON DELETE SET NULL decouples the
    product from the deleted category at the database level; SQLite (used
    here for fast unit tests) doesn't enforce foreign keys by default, so
    that specific cascade is verified against real Postgres instead — see
    the live smoke test in the phase report."""
    from app.models.product import Product

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    category = MenuCategory(restaurant_id=restaurant.id, name="Desserts")
    db.add(category)
    db.commit()
    product = Product(restaurant_id=restaurant.id, category_id=category.id, name="Gulab Jamun", price=Decimal("50.00"))
    db.add(product)
    db.commit()
    product_id = product.id
    category_id = category.id

    from app.services.products import delete_menu_category

    delete_menu_category(db, category)

    assert db.get(MenuCategory, category_id) is None
    assert db.get(Product, product_id) is not None


def test_owner_cannot_manage_another_owners_categories():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera@example.com", phone="9111111111")
            owner_b = _owner(seed, email="ownerb@example.com", phone="9222222222")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            category_b = MenuCategory(restaurant_id=restaurant_b.id, name="B's Pizza")
            seed.add(category_b)
            seed.commit()
            category_b_id = category_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token_a}"}

            # Owner A has no restaurant at all yet, so any restaurant-scoped
            # call resolves to "no restaurant" before it can even look at B's category.
            get_resp = client.get(f"/api/v1/restaurant/categories/{category_b_id}", headers=headers)
            assert get_resp.status_code == 404

            # Now give owner A their own restaurant and confirm cross-restaurant
            # category access is still rejected (the category simply isn't theirs).
            with Session(engine) as seed2:
                owner_a_db = seed2.query(User).filter(User.email == "ownera@example.com").first()
                _restaurant(seed2, owner_a_db, name="A's Diner")

            get_resp_2 = client.get(f"/api/v1/restaurant/categories/{category_b_id}", headers=headers)
            assert get_resp_2.status_code == 404

            patch_resp = client.patch(
                f"/api/v1/restaurant/categories/{category_b_id}", headers=headers, json={"name": "Hijacked"}
            )
            assert patch_resp.status_code == 404

            delete_resp = client.delete(f"/api/v1/restaurant/categories/{category_b_id}", headers=headers)
            assert delete_resp.status_code == 404
    finally:
        _teardown(engine)


def test_owner_cannot_use_restaurant_id_of_another_owner_to_list_categories():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera3@example.com", phone="9333333333")
            owner_b = _owner(seed, email="ownerb3@example.com", phone="9444444444")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            restaurant_b_id = restaurant_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/categories?restaurant_id={restaurant_b_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_category_management():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9555555555", password_hash="x", role=UserRole.CUSTOMER)
            seed.add(customer)
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/restaurant/categories", headers=headers).status_code == 403
            assert client.post("/api/v1/restaurant/categories", headers=headers, json={"name": "Pizza"}).status_code == 403
    finally:
        _teardown(engine)


def test_invalid_category_image_url_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/categories",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Pizza", "image_url": "not-a-url"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_blank_category_name_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/categories",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": ""},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)
