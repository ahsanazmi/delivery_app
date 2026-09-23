from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import MenuCategory, Product, Restaurant, User, UserRole
from app.services import products as product_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant(db, **overrides):
    owner = User(name="Owner", email=f"owner-{overrides.get('name', 'x')}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    payload = {
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("27.1234567"),
        "longitude": Decimal("82.1234567"),
        "minimum_order": Decimal("50.00"),
        "delivery_fee": Decimal("20.00"),
        "owner_id": owner.id,
        "is_active": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_products_hide_unavailable_and_inactive(db):
    restaurant = _restaurant(db)
    available = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
    sold_out = Product(restaurant_id=restaurant.id, name="Filter Coffee", price=Decimal("60.00"), is_available=False)
    removed = Product(restaurant_id=restaurant.id, name="Retired Item", price=Decimal("10.00"), is_active=False)
    db.add_all([available, sold_out, removed])
    db.commit()

    results = product_service.list_products(db, restaurant.id)
    assert [p.name for p in results] == ["Masala Dosa"]

    with pytest.raises(HTTPException, match="not found"):
        product_service.get_customer_visible_product_or_404(db, sold_out.id)


def test_products_filtered_by_menu_category(db):
    restaurant = _restaurant(db)
    starters = MenuCategory(restaurant_id=restaurant.id, name="Starters")
    mains = MenuCategory(restaurant_id=restaurant.id, name="Mains", display_order=1)
    db.add_all([starters, mains])
    db.commit()

    db.add_all([
        Product(restaurant_id=restaurant.id, category_id=starters.id, name="Samosa", price=Decimal("40.00")),
        Product(restaurant_id=restaurant.id, category_id=mains.id, name="Biryani", price=Decimal("220.00")),
    ])
    db.commit()

    starter_items = product_service.list_products(db, restaurant.id, category_id=starters.id)
    assert [p.name for p in starter_items] == ["Samosa"]

    categories = product_service.list_menu_categories(db, restaurant.id)
    assert [c.name for c in categories] == ["Starters", "Mains"]


def test_products_from_another_restaurant_are_not_returned(db):
    restaurant_a = _restaurant(db, name="a")
    restaurant_b = _restaurant(db, name="b")
    db.add(Product(restaurant_id=restaurant_a.id, name="A Item", price=Decimal("10.00")))
    db.add(Product(restaurant_id=restaurant_b.id, name="B Item", price=Decimal("20.00")))
    db.commit()

    results = product_service.list_products(db, restaurant_a.id)
    assert [p.name for p in results] == ["A Item"]


def test_customer_menu_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            restaurant = _restaurant(seed)
            mains = MenuCategory(restaurant_id=restaurant.id, name="Mains")
            seed.add(mains)
            seed.commit()
            product = Product(restaurant_id=restaurant.id, category_id=mains.id, name="Biryani", price=Decimal("220.00"), image_url="https://example.com/b.jpg")
            seed.add(product)
            seed.commit()
            restaurant_id, category_id, product_id = restaurant.id, mains.id, product.id

        with TestClient(app) as client:
            categories_response = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/categories")
            assert categories_response.status_code == 200
            assert categories_response.json()[0]["name"] == "Mains"

            products_response = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/products")
            assert products_response.status_code == 200
            body = products_response.json()
            assert len(body) == 1
            assert body[0]["name"] == "Biryani"
            assert body[0]["price"] == "220.00"

            detail_response = client.get(f"/api/v1/customer/products/{product_id}")
            assert detail_response.status_code == 200
            assert detail_response.json()["is_available"] is True

            missing_restaurant = client.get(
                "/api/v1/customer/restaurants/00000000-0000-0000-0000-000000000000/products"
            )
            assert missing_restaurant.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
