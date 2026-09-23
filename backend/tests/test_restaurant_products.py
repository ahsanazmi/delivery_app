"""Restaurant Owner Portal — Phase 6: product/menu management."""

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
from app.models.product import MenuCategory, Product


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


def test_create_and_list_products():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            create_resp = client.post(
                "/api/v1/restaurant/products",
                headers=headers,
                json={"name": "Butter Chicken", "description": "Creamy curry", "price": "280.00", "image_url": "https://example.com/bc.png"},
            )
            assert create_resp.status_code == 201
            body = create_resp.json()
            assert body["name"] == "Butter Chicken"
            assert body["price"] == "280.00"
            assert body["is_available"] is True
            assert body["category_id"] is None

            client.post("/api/v1/restaurant/products", headers=headers, json={"name": "Naan", "price": "40.00"})

            list_resp = client.get("/api/v1/restaurant/products", headers=headers)
            assert list_resp.status_code == 200
            names = sorted(p["name"] for p in list_resp.json())
            assert names == ["Butter Chicken", "Naan"]
    finally:
        _teardown(engine)


def test_create_product_with_valid_own_category():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            category = MenuCategory(restaurant_id=restaurant.id, name="Main Course")
            seed.add(category)
            seed.commit()
            category_id = category.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/products",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Biryani", "price": "220.00", "category_id": str(category_id)},
            )
            assert response.status_code == 201
            assert response.json()["category_id"] == str(category_id)
    finally:
        _teardown(engine)


def test_cannot_assign_product_to_another_restaurants_category():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera@example.com", phone="9111111111")
            owner_b = _owner(seed, email="ownerb@example.com", phone="9222222222")
            _restaurant(seed, owner_a, name="A's Diner")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            category_b = MenuCategory(restaurant_id=restaurant_b.id, name="B's Pizza")
            seed.add(category_b)
            seed.commit()
            category_b_id = category_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/products",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"name": "Sneaky Pizza", "price": "100.00", "category_id": str(category_b_id)},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_cannot_update_product_to_another_restaurants_category():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera2@example.com", phone="9333333333")
            owner_b = _owner(seed, email="ownerb2@example.com", phone="9444444444")
            restaurant_a = _restaurant(seed, owner_a, name="A's Diner")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            category_b = MenuCategory(restaurant_id=restaurant_b.id, name="B's Pizza")
            product_a = Product(restaurant_id=restaurant_a.id, name="Pasta", price=Decimal("150.00"))
            seed.add_all([category_b, product_a])
            seed.commit()
            category_b_id = category_b.id
            product_a_id = product_a.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/restaurant/products/{product_a_id}",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"category_id": str(category_b_id)},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_patch_product_updates_fields_and_availability():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            product = Product(restaurant_id=restaurant.id, name="Naan", price=Decimal("40.00"), is_available=True)
            seed.add(product)
            seed.commit()
            product_id = product.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/restaurant/products/{product_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"price": "45.00", "is_available": False, "description": "Out of stock today"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["price"] == "45.00"
            assert body["is_available"] is False
            assert body["description"] == "Out of stock today"
    finally:
        _teardown(engine)


def test_patch_product_can_clear_category(db):
    from app.services.products import create_product, update_product
    from app.schemas.product import ProductCreate, ProductUpdate

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    category = MenuCategory(restaurant_id=restaurant.id, name="Drinks")
    db.add(category)
    db.commit()

    product = create_product(db, restaurant.id, ProductCreate(name="Chai", price=Decimal("30.00"), category_id=category.id))
    assert product.category_id == category.id

    updated = update_product(db, restaurant.id, product, ProductUpdate(category_id=None))
    assert updated.category_id is None


def test_delete_product_soft_deletes_it(db):
    """Data Consistency Audit — delete_product is a soft delete
    (is_active=False), not a hard one: a hard delete would cascade-delete
    any CartItem still pointing at it (real FK, ON DELETE CASCADE) before
    sync_cart_with_catalog ever gets a chance to notice and report the
    removal to the customer. The row itself must survive."""
    from app.services.products import delete_product

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    product = Product(restaurant_id=restaurant.id, name="Naan", price=Decimal("40.00"))
    db.add(product)
    db.commit()
    product_id = product.id

    delete_product(db, product)
    survivor = db.get(Product, product_id)
    assert survivor is not None
    assert survivor.is_active is False


def test_deleted_product_disappears_from_owner_list_and_get_and_customer_catalog():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            product = Product(restaurant_id=restaurant.id, name="Naan", price=Decimal("40.00"))
            seed.add(product)
            seed.commit()
            product_id = product.id
            restaurant_id = restaurant.id
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            delete = client.delete(f"/api/v1/restaurant/products/{product_id}", headers=headers)
            assert delete.status_code == 204

            # Gone from the owner's own list.
            owner_list = client.get("/api/v1/restaurant/products", headers=headers)
            assert all(p["id"] != str(product_id) for p in owner_list.json())

            # A direct GET/PATCH/second-DELETE on it is now a clean 404, not
            # a silent success or a crash on an already-deleted row.
            assert client.get(f"/api/v1/restaurant/products/{product_id}", headers=headers).status_code == 404
            assert client.patch(f"/api/v1/restaurant/products/{product_id}", headers=headers, json={"price": "50.00"}).status_code == 404
            assert client.delete(f"/api/v1/restaurant/products/{product_id}", headers=headers).status_code == 404

            # Gone from customer-facing discovery too.
            public = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/products")
            assert all(p["id"] != str(product_id) for p in public.json())
    finally:
        _teardown(engine)


def test_deleting_a_product_already_in_a_customers_cart_is_reported_not_silently_dropped():
    """The actual bug this phase's audit found: a hard delete's ON DELETE
    CASCADE on CartItem.product_id silently removed the cart item with no
    removed_items notice. Soft-deleting keeps the row so
    sync_cart_with_catalog's existing is_active check catches and reports it."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            customer = User(name="Cart Customer", email="cart-customer-delete@example.com", phone="9500000099", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
            seed.add(customer)
            seed.commit()
            product = Product(restaurant_id=restaurant.id, name="Doomed Item", price=Decimal("99.00"))
            seed.add(product)
            seed.commit()
            product_id = product.id
            owner_token = create_access_token(owner.id)
            customer_token = create_access_token(customer.id)

        with TestClient(app) as client:
            owner_headers = {"Authorization": f"Bearer {owner_token}"}
            customer_headers = {"Authorization": f"Bearer {customer_token}"}

            added = client.post(
                "/api/v1/customer/cart/items", headers=customer_headers,
                json={"product_id": str(product_id), "quantity": 2},
            )
            assert added.status_code == 201

            assert client.delete(f"/api/v1/restaurant/products/{product_id}", headers=owner_headers).status_code == 204

            cart = client.get("/api/v1/customer/cart", headers=customer_headers)
            assert cart.json()["items"] == []
            assert cart.json()["removed_items"] == ["Doomed Item"]
    finally:
        _teardown(engine)


def test_owner_cannot_manage_another_owners_products():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera3@example.com", phone="9555555555")
            owner_b = _owner(seed, email="ownerb3@example.com", phone="9666666666")
            restaurant_a = _restaurant(seed, owner_a, name="A's Diner")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            product_b = Product(restaurant_id=restaurant_b.id, name="B's Pizza", price=Decimal("100.00"))
            seed.add(product_b)
            seed.commit()
            product_b_id = product_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token_a}"}
            assert client.get(f"/api/v1/restaurant/products/{product_b_id}", headers=headers).status_code == 404
            assert client.patch(
                f"/api/v1/restaurant/products/{product_b_id}", headers=headers, json={"name": "Hijacked"}
            ).status_code == 404
            assert client.delete(f"/api/v1/restaurant/products/{product_b_id}", headers=headers).status_code == 404
    finally:
        _teardown(engine)


def test_owner_cannot_list_another_owners_products_via_restaurant_id():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, email="ownera4@example.com", phone="9777777777")
            owner_b = _owner(seed, email="ownerb4@example.com", phone="9888888888")
            restaurant_b = _restaurant(seed, owner_b, name="B's Diner")
            restaurant_b_id = restaurant_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/products?restaurant_id={restaurant_b_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_customer_and_rider_cannot_access_product_management():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = User(name="C", email="c@example.com", phone="9999999999", password_hash="x", role=UserRole.CUSTOMER)
            seed.add(customer)
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/restaurant/products", headers=headers).status_code == 403
            assert client.post("/api/v1/restaurant/products", headers=headers, json={"name": "x", "price": "1.00"}).status_code == 403
    finally:
        _teardown(engine)


def test_zero_or_negative_price_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.post("/api/v1/restaurant/products", headers=headers, json={"name": "Free Item", "price": "0.00"}).status_code == 422
            assert client.post("/api/v1/restaurant/products", headers=headers, json={"name": "Negative", "price": "-5.00"}).status_code == 422
    finally:
        _teardown(engine)


def test_blank_product_name_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/products",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "", "price": "10.00"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_invalid_product_image_url_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurant/products",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Pizza", "price": "10.00", "image_url": "not-a-url"},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)


def test_nonexistent_category_id_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            import uuid

            response = client.post(
                "/api/v1/restaurant/products",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Pizza", "price": "10.00", "category_id": str(uuid.uuid4())},
            )
            assert response.status_code == 422
    finally:
        _teardown(engine)
