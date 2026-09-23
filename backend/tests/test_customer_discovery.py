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
from app.models import Category, Restaurant, User, UserRole
from app.services import categories as category_service
from app.services import restaurants as restaurant_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com"):
    owner = User(name="Owner", email=email, password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    return owner


def _restaurant(db, owner, **overrides):
    payload = {
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road, Itwa",
        "latitude": Decimal("27.1234567"),
        "longitude": Decimal("82.1234567"),
        "minimum_order": Decimal("50.00"),
        "delivery_fee": Decimal("20.00"),
        "owner_id": owner.id,
        "is_active": True,
        "is_open": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_customer_listing_excludes_inactive_but_includes_closed(db):
    owner = _owner(db)
    open_restaurant = _restaurant(db, owner, name="Open Place")
    closed_restaurant = _restaurant(db, owner, name="Closed Place", is_open=False)
    _restaurant(db, owner, name="Inactive Place", is_active=False)

    results = restaurant_service.list_active_restaurants(db, open_only=False, offset=0, limit=20)
    names = {r.name for r in results}
    assert names == {"Open Place", "Closed Place"}
    assert open_restaurant in results
    assert closed_restaurant in results


def test_customer_listing_can_filter_by_category(db):
    owner = _owner(db)
    pizza = Category(name="Pizza")
    burgers = Category(name="Burgers")
    db.add_all([pizza, burgers])
    db.commit()

    _restaurant(db, owner, name="Pizza Place", category_id=pizza.id)
    _restaurant(db, owner, name="Burger Place", category_id=burgers.id)

    results = restaurant_service.list_active_restaurants(db, open_only=False, offset=0, limit=20, category_id=pizza.id)
    assert [r.name for r in results] == ["Pizza Place"]


def test_category_service_hides_inactive_categories(db):
    active = Category(name="Pizza", display_order=1)
    inactive = Category(name="Retired", is_active=False)
    db.add_all([active, inactive])
    db.commit()

    results = category_service.list_active_categories(db)
    assert [c.name for c in results] == ["Pizza"]

    with pytest.raises(HTTPException, match="not found"):
        category_service.get_active_category_or_404(db, inactive.id)


def test_customer_restaurant_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            category = Category(name="Pizza")
            seed.add(category)
            seed.commit()
            restaurant = _restaurant(seed, owner, category_id=category.id, delivery_time_minutes=25)
            restaurant_id = restaurant.id
            category_id = category.id

        with TestClient(app) as client:
            categories_response = client.get("/api/v1/customer/categories")
            assert categories_response.status_code == 200
            assert categories_response.json()[0]["name"] == "Pizza"

            list_response = client.get("/api/v1/customer/restaurants", params={"category_id": str(category_id)})
            assert list_response.status_code == 200
            body = list_response.json()
            assert len(body) == 1
            assert body[0]["rating"] == "0.00"
            assert body[0]["delivery_time_minutes"] == 25
            assert "owner_id" not in body[0]

            detail_response = client.get(f"/api/v1/customer/restaurants/{restaurant_id}")
            assert detail_response.status_code == 200
            assert detail_response.json()["name"] == "Chai House"

            missing_category = client.get("/api/v1/customer/categories/00000000-0000-0000-0000-000000000000")
            assert missing_category.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
