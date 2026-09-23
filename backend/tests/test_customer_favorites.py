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
from app.models import Restaurant, User, UserRole
from app.services.favorites import add_favorite, list_favorite_restaurants, remove_favorite


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, name="Chai House", **overrides):
    owner = User(name="Owner", email=f"owner-{name}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    payload = {
        "owner_id": owner.id,
        "name": name,
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("12.1"),
        "longitude": Decimal("77.1"),
        "minimum_order": Decimal("0.00"),
        "delivery_fee": Decimal("0.00"),
        "is_active": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    return restaurant


def test_add_and_list_favorites(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    add_favorite(db, customer.id, restaurant.id)
    favorites = list_favorite_restaurants(db, customer.id)
    assert [r.name for r in favorites] == ["Chai House"]


def test_adding_favorite_twice_is_idempotent(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    add_favorite(db, customer.id, restaurant.id)
    add_favorite(db, customer.id, restaurant.id)
    favorites = list_favorite_restaurants(db, customer.id)
    assert len(favorites) == 1


def test_remove_favorite(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    add_favorite(db, customer.id, restaurant.id)
    remove_favorite(db, customer.id, restaurant.id)
    assert list_favorite_restaurants(db, customer.id) == []


def test_removing_favorite_never_added_is_a_noop(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    remove_favorite(db, customer.id, restaurant.id)
    assert list_favorite_restaurants(db, customer.id) == []


def test_cannot_favorite_inactive_restaurant(db):
    customer = _customer(db)
    restaurant = _restaurant(db, is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        add_favorite(db, customer.id, restaurant.id)
    assert exc_info.value.status_code == 404


def test_favorites_are_scoped_per_customer(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)

    add_favorite(db, customer.id, restaurant.id)
    assert list_favorite_restaurants(db, other.id) == []
    assert len(list_favorite_restaurants(db, customer.id)) == 1


def test_favorites_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            restaurant_id = restaurant.id
            from app.core.security import create_access_token

            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}

            empty = client.get("/api/v1/customer/favorites", headers=headers)
            assert empty.status_code == 200
            assert empty.json() == []

            add = client.post(f"/api/v1/customer/favorites/{restaurant_id}", headers=headers)
            assert add.status_code == 204

            listing = client.get("/api/v1/customer/favorites", headers=headers)
            assert listing.status_code == 200
            assert len(listing.json()) == 1
            assert listing.json()[0]["id"] == str(restaurant_id)

            remove = client.delete(f"/api/v1/customer/favorites/{restaurant_id}", headers=headers)
            assert remove.status_code == 204

            after_remove = client.get("/api/v1/customer/favorites", headers=headers)
            assert after_remove.json() == []
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
