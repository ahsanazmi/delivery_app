from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Restaurant, User, UserRole
from app.schemas.restaurant import RestaurantCreate, RestaurantUpdate
from app.services import restaurants as restaurant_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def restaurant_payload(**overrides):
    payload = {
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road, Itwa, Siddharthnagar",
        "latitude": Decimal("27.1234567"),
        "longitude": Decimal("82.1234567"),
        "minimum_order": Decimal("50.00"),
        "delivery_fee": Decimal("20.00"),
    }
    payload.update(overrides)
    return RestaurantCreate(**payload)


def test_restaurant_owner_can_create_manage_and_deactivate(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT)
    db.add(owner)
    db.commit()

    restaurant = restaurant_service.create_restaurant(db, restaurant_payload(), owner)
    assert restaurant.owner_id == owner.id
    assert restaurant.is_open is True
    assert restaurant_service.list_active_restaurants(db, open_only=True, offset=0, limit=20) == [restaurant]

    restaurant_service.update_restaurant(db, restaurant, RestaurantUpdate(name="New Chai House"))
    assert restaurant.name == "New Chai House"
    restaurant_service.deactivate_restaurant(db, restaurant)
    assert restaurant.is_active is False
    assert restaurant.is_open is False
    assert restaurant_service.list_active_restaurants(db, open_only=False, offset=0, limit=20) == []


def test_owner_cannot_manage_another_restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT)
    other_owner = User(name="Other", email="other@example.com", password_hash="x", role=UserRole.RESTAURANT)
    db.add_all([owner, other_owner])
    db.commit()
    restaurant = restaurant_service.create_restaurant(db, restaurant_payload(), owner)

    with pytest.raises(HTTPException, match="do not manage"):
        restaurant_service.assert_restaurant_manager(restaurant, other_owner)
