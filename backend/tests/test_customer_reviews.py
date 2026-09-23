from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.schemas.review import OrderReviewCreate
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.reviews import create_order_review, get_order_review, update_order_review


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


def _restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id,
        name="Chai House",
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, customer, restaurant):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _deliver(db, order, rider):
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()


def test_cannot_review_undelivered_order(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    with pytest.raises(HTTPException) as exc_info:
        create_order_review(db, customer.id, order.id, restaurant_rating=5, delivery_rating=5, comment="Great")
    assert exc_info.value.status_code == 409


def test_can_review_delivered_order(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    _deliver(db, order, rider)

    review = create_order_review(db, customer.id, order.id, restaurant_rating=4, delivery_rating=5, comment="Tasty")
    assert review.restaurant_rating == 4
    assert review.delivery_rating == 5
    assert review.order_id == order.id


def test_cannot_review_same_order_twice(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    _deliver(db, order, rider)
    create_order_review(db, customer.id, order.id, restaurant_rating=4, delivery_rating=5, comment=None)

    with pytest.raises(HTTPException) as exc_info:
        create_order_review(db, customer.id, order.id, restaurant_rating=3, delivery_rating=3, comment=None)
    assert exc_info.value.status_code == 409


def test_only_order_owner_can_review(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    _deliver(db, order, rider)

    with pytest.raises(HTTPException) as exc_info:
        create_order_review(db, other.id, order.id, restaurant_rating=5, delivery_rating=5, comment=None)
    assert exc_info.value.status_code == 404


def test_only_reviewer_can_update_their_review(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    _deliver(db, order, rider)
    review = create_order_review(db, customer.id, order.id, restaurant_rating=4, delivery_rating=4, comment=None)

    with pytest.raises(HTTPException) as exc_info:
        update_order_review(db, other.id, review.id, restaurant_rating=1, delivery_rating=1, comment=None)
    assert exc_info.value.status_code == 404

    updated = update_order_review(db, customer.id, review.id, restaurant_rating=5, delivery_rating=None, comment="Updated")
    assert updated.restaurant_rating == 5
    assert updated.delivery_rating == 4  # unchanged
    assert updated.comment == "Updated"


def test_invalid_rating_rejected_by_schema():
    with pytest.raises(ValidationError):
        OrderReviewCreate(restaurant_rating=6, delivery_rating=3, comment=None)
    with pytest.raises(ValidationError):
        OrderReviewCreate(restaurant_rating=0, delivery_rating=3, comment=None)


def test_get_order_review_returns_none_when_not_yet_reviewed(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_order(db, customer, restaurant)
    _deliver(db, order, rider)

    assert get_order_review(db, customer.id, order.id) is None


def test_review_endpoints_over_http():
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
            rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
            seed.add(rider)
            seed.commit()
            order = _place_order(seed, customer, restaurant)
            _deliver(seed, order, rider)
            order_id = order.id
            from app.core.security import create_access_token

            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}

            empty = client.get(f"/api/v1/customer/orders/{order_id}/review", headers=headers)
            assert empty.status_code == 200
            assert empty.json() is None

            create = client.post(
                f"/api/v1/customer/orders/{order_id}/review",
                headers=headers,
                json={"restaurant_rating": 5, "delivery_rating": 4, "comment": "Loved it"},
            )
            assert create.status_code == 201
            review_id = create.json()["id"]

            fetched = client.get(f"/api/v1/customer/orders/{order_id}/review", headers=headers)
            assert fetched.status_code == 200
            assert fetched.json()["id"] == review_id

            invalid = client.post(
                f"/api/v1/customer/orders/{order_id}/review",
                headers=headers,
                json={"restaurant_rating": 9, "delivery_rating": 4},
            )
            assert invalid.status_code == 422

            patch = client.patch(
                f"/api/v1/customer/reviews/{review_id}", headers=headers, json={"comment": "Even better on reflection"}
            )
            assert patch.status_code == 200
            assert patch.json()["comment"] == "Even better on reflection"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
