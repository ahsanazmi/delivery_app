from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.schemas.review import OrderReviewCreate
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.reviews import _normalize_comment, create_order_review
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


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
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
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
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()
    return order


# --- rating: integer, 1-5 -----------------------------------------------

@pytest.mark.parametrize("rating", [0, -1, 6, 100])
def test_rating_outside_1_to_5_is_rejected(rating):
    with pytest.raises(ValidationError):
        OrderReviewCreate(restaurant_rating=rating, delivery_rating=3, comment=None)


def test_non_integer_rating_is_rejected():
    with pytest.raises(ValidationError):
        OrderReviewCreate(restaurant_rating=4.5, delivery_rating=3, comment=None)


def test_whole_number_float_rating_is_accepted_as_the_equivalent_integer():
    # Pydantic v2's lax int mode allows a lossless float like 4.0 -> 4;
    # this isn't a gap, it's standard JSON-number handling (JSON has no
    # separate int/float wire type) and the stored value is still a plain int.
    payload = OrderReviewCreate(restaurant_rating=4.0, delivery_rating=5, comment=None)
    assert payload.restaurant_rating == 4
    assert isinstance(payload.restaurant_rating, int)


# --- comment: length, whitespace, empty, Unicode -------------------------

def test_comment_over_max_length_is_rejected():
    with pytest.raises(ValidationError):
        OrderReviewCreate(restaurant_rating=5, delivery_rating=5, comment="x" * 1001)


def test_comment_at_max_length_is_accepted():
    payload = OrderReviewCreate(restaurant_rating=5, delivery_rating=5, comment="x" * 1000)
    assert len(payload.comment) == 1000


def test_normalize_comment_treats_whitespace_only_as_no_comment():
    assert _normalize_comment("   ") is None
    assert _normalize_comment("\n\t  \n") is None
    assert _normalize_comment("") is None
    assert _normalize_comment(None) is None


def test_normalize_comment_trims_surrounding_whitespace_but_keeps_content():
    assert _normalize_comment("  Great food!  ") == "Great food!"


def test_normalize_comment_passes_multilingual_unicode_through_unchanged():
    # Hindi (Devanagari), Arabic, Japanese, and an emoji — none of this
    # should be rejected, altered, or mangled.
    samples = [
        "खाना बहुत बढ़िया था, जल्दी डिलीवरी हुई 🙂",
        "الطعام كان رائعا والتوصيل سريع",
        "とても美味しかったです、また注文します",
    ]
    for text in samples:
        assert _normalize_comment(text) == text


def test_whitespace_only_comment_is_stored_as_null_through_the_full_create_flow(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _delivered_order(db, customer, restaurant, rider)

    review = create_order_review(db, customer.id, order.id, restaurant_rating=5, delivery_rating=5, comment="    ")
    assert review.comment is None


def test_multilingual_comment_survives_the_full_create_flow_unchanged(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    order = _delivered_order(db, customer, restaurant, rider)

    text = "खाना बहुत बढ़िया था 🙂 とても美味しかったです"
    review = create_order_review(db, customer.id, order.id, restaurant_rating=5, delivery_rating=5, comment=text)
    assert review.comment == text
