from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Category, MenuCategory, Product, Restaurant, User, UserRole
from app.services.search import run_customer_search


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant(db, name, category_id=None, is_active=True):
    owner = User(name="Owner", email=f"owner-{name}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id,
        name=name,
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("27.1234567"),
        longitude=Decimal("82.1234567"),
        minimum_order=Decimal("50.00"),
        delivery_fee=Decimal("20.00"),
        category_id=category_id,
        is_active=is_active,
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_search_matches_restaurants_products_and_categories_by_name(db):
    pizza = Category(name="Pizza")
    db.add(pizza)
    db.commit()

    restaurant = _restaurant(db, "Pizza Palace", category_id=pizza.id)
    other = _restaurant(db, "Burger Barn")
    db.add(Product(restaurant_id=restaurant.id, name="Margherita Pizza", price=Decimal("199.00")))
    db.add(Product(restaurant_id=other.id, name="Cheeseburger", price=Decimal("150.00")))
    db.commit()

    result = run_customer_search(db, q="pizza", category_id=None, restaurant_id=None, page=1, limit=20)
    assert [r.name for r in result["restaurants"]] == ["Pizza Palace"]
    assert [p.name for p in result["products"]] == ["Margherita Pizza"]
    assert [c.name for c in result["categories"]] == ["Pizza"]


def test_search_excludes_inactive_restaurant_products(db):
    restaurant = _restaurant(db, "Closed Down", is_active=False)
    db.add(Product(restaurant_id=restaurant.id, name="Ghost Combo", price=Decimal("10.00")))
    db.commit()

    result = run_customer_search(db, q="ghost", category_id=None, restaurant_id=None, page=1, limit=20)
    assert result["products"] == []
    assert result["restaurants"] == []


def test_search_filters_products_by_restaurant_and_menu_category(db):
    restaurant_a = _restaurant(db, "A House")
    restaurant_b = _restaurant(db, "B House")
    mains = MenuCategory(restaurant_id=restaurant_a.id, name="Mains")
    db.add(mains)
    db.commit()

    db.add_all([
        Product(restaurant_id=restaurant_a.id, category_id=mains.id, name="Chicken Curry", price=Decimal("180.00")),
        Product(restaurant_id=restaurant_b.id, name="Chicken Wrap", price=Decimal("120.00")),
    ])
    db.commit()

    result = run_customer_search(
        db, q="chicken", category_id=None, restaurant_id=restaurant_a.id, page=1, limit=20
    )
    assert [p.name for p in result["products"]] == ["Chicken Curry"]

    result_by_menu_category = run_customer_search(
        db, q=None, category_id=mains.id, restaurant_id=None, page=1, limit=20
    )
    assert [p.name for p in result_by_menu_category["products"]] == ["Chicken Curry"]


def test_search_pagination():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
            seed.add(owner)
            seed.commit()
            for i in range(3):
                seed.add(
                    Restaurant(
                        owner_id=owner.id,
                        name=f"Curry Spot {i}",
                        phone="9876543210",
                        address="Main Road",
                        latitude=Decimal("27.1234567"),
                        longitude=Decimal("82.1234567"),
                        minimum_order=Decimal("50.00"),
                        delivery_fee=Decimal("20.00"),
                    )
                )
            seed.commit()

        with TestClient(app) as client:
            page1 = client.get("/api/v1/customer/search", params={"q": "curry", "limit": 2, "page": 1})
            assert page1.status_code == 200
            body1 = page1.json()
            assert len(body1["restaurants"]) == 2
            assert body1["page"] == 1

            page2 = client.get("/api/v1/customer/search", params={"q": "curry", "limit": 2, "page": 2})
            body2 = page2.json()
            assert len(body2["restaurants"]) == 1
            assert {r["name"] for r in body1["restaurants"]} != {r["name"] for r in body2["restaurants"]}
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
