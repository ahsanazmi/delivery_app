from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Coupon, Restaurant, User, UserRole
from app.services.coupons import calculate_coupon_discount
from app.services.restaurants import search_restaurants


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_search_restaurants_by_name(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()

    db.add_all(
        [
            Restaurant(
                owner_id=owner.id,
                name="Biryani House",
                phone="9876543210",
                address="Main Road",
                latitude=Decimal("12.1"),
                longitude=Decimal("77.1"),
                minimum_order=Decimal("100.00"),
                delivery_fee=Decimal("20.00"),
                average_rating=Decimal("4.5"),
            ),
            Restaurant(
                owner_id=owner.id,
                name="Paneer Corner",
                phone="9876543211",
                address="Second Road",
                latitude=Decimal("12.2"),
                longitude=Decimal("77.2"),
                minimum_order=Decimal("120.00"),
                delivery_fee=Decimal("25.00"),
                average_rating=Decimal("4.0"),
            ),
        ]
    )
    db.commit()

    results = search_restaurants(db, "biryani")
    assert [restaurant.name for restaurant in results] == ["Biryani House"]


def test_coupon_discount_logic_and_status(db):
    coupon = Coupon(
        code="WELCOME50",
        discount_type="percent",
        discount_value=Decimal("50"),
        min_order=Decimal("300.00"),
        max_discount=Decimal("150.00"),
        usage_limit=10,
        is_active=True,
    )

    discount = calculate_coupon_discount(coupon, Decimal("600.00"))
    assert discount == Decimal("150.00")
    assert coupon.is_active is True
