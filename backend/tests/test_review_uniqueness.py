from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.models.review import Review
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.reviews import create_order_review


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db):
    user = User(name="Customer", email="customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
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


def _delivered_order(db, customer, restaurant, rider):
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


def test_application_layer_rejects_a_second_review_for_the_same_order(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _delivered_order(db, customer, restaurant, rider)

    create_order_review(db, customer.id, order.id, restaurant_rating=5, delivery_rating=5, comment="Great")

    with pytest.raises(HTTPException) as exc_info:
        create_order_review(db, customer.id, order.id, restaurant_rating=1, delivery_rating=1, comment="Again")
    assert exc_info.value.status_code == 409


def test_database_constraint_rejects_a_duplicate_order_id_even_bypassing_the_application_check(db):
    """Phase 8 — the uq_reviews_order_id constraint must independently reject
    a duplicate, not just the application-layer existence check above. This
    writes the second row directly through the ORM, bypassing
    create_order_review's own duplicate check entirely, to prove the
    database itself — not just the service function — is the backstop."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _delivered_order(db, customer, restaurant, rider)

    first = Review(
        user_id=customer.id,
        order_id=order.id,
        restaurant_id=restaurant.id,
        rider_id=rider.id,
        target_type="restaurant",
        target_id=str(restaurant.id),
        rating=5,
        restaurant_rating=5,
        delivery_rating=5,
    )
    db.add(first)
    db.commit()

    second = Review(
        user_id=customer.id,
        order_id=order.id,  # same order_id — the database must reject this on its own
        restaurant_id=restaurant.id,
        rider_id=rider.id,
        target_type="restaurant",
        target_id=str(restaurant.id),
        rating=1,
        restaurant_rating=1,
        delivery_rating=1,
    )
    db.add(second)
    with pytest.raises(Exception):  # sqlalchemy.exc.IntegrityError on every backend this runs against
        db.commit()
    db.rollback()

    assert db.query(Review).filter(Review.order_id == order.id).count() == 1


def test_the_database_constraint_still_stops_a_genuine_commit_time_race(tmp_path):
    """Phase 8's real target: the TOCTOU race where two requests both pass a
    duplicate pre-check (`existing = db.query(...).first()`, as
    create_order_review runs) before either commits. A single in-memory
    SQLite connection can't model two interleaved transactions, so this
    uses a real file-backed SQLite database and two separate
    sessions/connections, manually interleaved to reproduce exactly that
    race: session A's pre-check runs and sees nothing, then session B
    independently inserts and commits first, then session A's own insert
    hits the constraint on commit. This is the scenario
    create_order_review's `except IntegrityError` handler exists for —
    proving the database genuinely raises IntegrityError here (rather than
    silently allowing both rows) is what makes that handler meaningful
    rather than dead code."""
    db_path = tmp_path / "review_race.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as setup:
        customer = _customer(setup)
        restaurant = _restaurant(setup)
        rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
        setup.add(rider)
        setup.commit()
        order = _delivered_order(setup, customer, restaurant, rider)
        customer_id, restaurant_id, rider_id, order_id = customer.id, restaurant.id, rider.id, order.id

    session_a = Session(engine)
    session_b = Session(engine)
    try:
        # Session A: run create_order_review's own pre-check manually so we
        # can pause before its commit — at this point no review exists yet.
        assert session_a.query(Review).filter(Review.order_id == order_id).first() is None

        # Session B now wins the race: inserts and commits first.
        winner = Review(
            user_id=customer_id,
            order_id=order_id,
            restaurant_id=restaurant_id,
            rider_id=rider_id,
            target_type="restaurant",
            target_id=str(restaurant_id),
            rating=5,
            restaurant_rating=5,
            delivery_rating=5,
        )
        session_b.add(winner)
        session_b.commit()

        # Session A proceeds as create_order_review would have — its own
        # pre-check already ran and saw nothing, so it goes straight to the
        # INSERT + commit, which must now hit the real constraint.
        loser = Review(
            user_id=customer_id,
            order_id=order_id,
            restaurant_id=restaurant_id,
            rider_id=rider_id,
            target_type="restaurant",
            target_id=str(restaurant_id),
            rating=1,
            restaurant_rating=1,
            delivery_rating=1,
        )
        session_a.add(loser)
        with pytest.raises(IntegrityError):
            session_a.commit()
        session_a.rollback()

        assert session_a.query(Review).filter(Review.order_id == order_id).count() == 1
    finally:
        session_a.close()
        session_b.close()
