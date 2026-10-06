from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Restaurant, User, UserRole
from app.models.review import Review, ReviewStatus, ReviewTarget
from app.services.orders import create_order, transition_order_status, assign_rider_to_order
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.models import Product
from app.services.reviews import average_rating_for_target, create_order_review, create_review, list_reviews_for_target


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


def _place_and_deliver_order(db, customer, restaurant, rider):
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
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()
    return order


def test_new_order_review_defaults_to_published(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _place_and_deliver_order(db, customer, restaurant, rider)

    review = create_order_review(db, customer.id, order.id, restaurant_rating=5, delivery_rating=5, comment="Great")
    assert review.status == ReviewStatus.PUBLISHED


def test_new_generic_review_defaults_to_published(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    review = create_review(
        db,
        user_id=customer.id,
        target_type=ReviewTarget.RESTAURANT,
        target_id=str(restaurant.id),
        rating=4,
        comment="Nice",
        restaurant_id=restaurant.id,
    )
    assert review.status == ReviewStatus.PUBLISHED


def test_hidden_and_removed_reviews_are_excluded_from_public_list(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    published = create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=5, comment="Good", restaurant_id=restaurant.id)
    hidden = create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=1, comment="Bad", restaurant_id=restaurant.id)
    flagged = create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=1, comment="Spam", restaurant_id=restaurant.id)
    removed = create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=1, comment="Gone", restaurant_id=restaurant.id)

    hidden.status = ReviewStatus.HIDDEN
    flagged.status = ReviewStatus.FLAGGED
    removed.status = ReviewStatus.REMOVED
    db.commit()

    visible = list_reviews_for_target(db, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id))
    visible_ids = {review.id for review in visible}

    assert visible_ids == {published.id}
    assert hidden.id not in visible_ids
    assert flagged.id not in visible_ids
    assert removed.id not in visible_ids


def test_average_rating_only_counts_published_reviews(db):
    customer = _customer(db)
    restaurant = _restaurant(db)

    create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=5, comment=None, restaurant_id=restaurant.id)
    removed = create_review(db, user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id), rating=1, comment=None, restaurant_id=restaurant.id)
    removed.status = ReviewStatus.REMOVED
    db.commit()

    # Only the single published 5-star review should count — if the removed
    # 1-star review leaked in, the average would be 3.0, not 5.0.
    assert average_rating_for_target(db, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant.id)) == 5.0


def test_removed_review_not_exposed_over_public_http_endpoint():
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

            visible = Review(user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant_id), rating=5, comment="Loved it", restaurant_id=restaurant_id, status=ReviewStatus.PUBLISHED)
            removed = Review(user_id=customer.id, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant_id), rating=1, comment="Should not appear", restaurant_id=restaurant_id, status=ReviewStatus.REMOVED)
            seed.add_all([visible, removed])
            seed.commit()

        with TestClient(app) as client:
            response = client.get(f"/api/v1/reviews/restaurant/{restaurant_id}")
            assert response.status_code == 200
            comments = [item["comment"] for item in response.json()]
            assert comments == ["Loved it"]
            assert "Should not appear" not in comments
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
