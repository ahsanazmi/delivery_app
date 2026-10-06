"""Maps & Location System Phase 20 — Restaurant → Customer Route."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.schemas.location import RouteResult
from app.services import orders as orders_service
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, get_order_route_info
from app.services.routing import RouteUnavailableError


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db):
    user = User(name="Owner", email="owner-p20@example.com", phone="9000000030", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner):
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("26.068"), longitude=Decimal("83.1836"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, *, latitude=None, longitude=None):
    customer = User(name="Cust", email="cust-p20@example.com", phone="9200000030", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "latitude": latitude, "longitude": longitude,
    })
    return create_order(db, customer, address.id)


def test_restaurant_order_detail_includes_rider_location_while_actively_delivering(db):
    """Live Rider Tracking Phase 27 — Restaurant/Admin Visibility."""
    from datetime import UTC, datetime

    from app.models.order import OrderStatus

    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)
    rider = User(name="Rider", email="p27-rest-rider@example.com", phone="9300000030", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order.rider_id = rider.id
    order.status = OrderStatus.OUT_FOR_DELIVERY
    rider.current_latitude = Decimal("26.09")
    rider.current_longitude = Decimal("83.19")
    rider.location_updated_at = datetime.now(UTC)
    db.commit()
    token = create_access_token(owner.id)
    order_id = order.id

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/restaurant/orders/{order_id}", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["rider_latitude"]) == Decimal("26.09")
        assert Decimal(body["rider_longitude"]) == Decimal("83.19")
    finally:
        app.dependency_overrides.clear()


def test_get_order_route_info_returns_none_when_the_order_has_no_coordinates(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)

    assert get_order_route_info(order, restaurant) is None


def test_get_order_route_info_delegates_to_location_service(db, monkeypatch):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, latitude=Decimal("26.1"), longitude=Decimal("83.2"))

    mocked = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.1))
    monkeypatch.setattr(orders_service.location_service, "route", mocked)

    result = get_order_route_info(order, restaurant)

    mocked.assert_called_once_with(restaurant.latitude, restaurant.longitude, order.latitude, order.longitude)
    assert result == RouteResult(distance_km=4.3, duration_minutes=9.1)


def test_route_endpoint_returns_null_route_when_the_order_has_no_coordinates(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)
    token = create_access_token(owner.id)

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order.id}/route", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == 200
        assert response.json()["route"] is None
    finally:
        app.dependency_overrides.clear()


def test_route_endpoint_returns_503_when_the_provider_is_unavailable(db, monkeypatch):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant, latitude=Decimal("26.1"), longitude=Decimal("83.2"))
    token = create_access_token(owner.id)

    def raise_unavailable(*args, **kwargs):
        raise RouteUnavailableError("Route calculation is temporarily unavailable.")

    monkeypatch.setattr(orders_service.location_service, "route", raise_unavailable)

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order.id}/route", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_route_endpoint_requires_restaurant_owner_role(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)
    customer = User(name="Someone", email="someone-p20@example.com", phone="9300000030", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    token = create_access_token(customer.id)

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order.id}/route", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_route_endpoint_404s_for_another_restaurants_order(db):
    owner_a = _owner(db)
    restaurant_a = _restaurant(db, owner_a)
    order = _place_order(db, restaurant_a)

    owner_b = User(name="Owner B", email="owner-b-p20@example.com", phone="9400000030", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner_b)
    db.commit()
    restaurant_b = Restaurant(
        owner_id=owner_b.id, name="Other Place", phone="9876500001", address="Other Road",
        latitude=Decimal("26.1"), longitude=Decimal("83.2"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant_b)
    db.commit()
    token = create_access_token(owner_b.id)

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order.id}/route", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
