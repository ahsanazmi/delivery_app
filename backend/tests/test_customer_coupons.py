from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Coupon, CouponRedemption, DiscountType, Product, Restaurant, User, UserRole
from app.services.cart import add_item, calculate_cart_totals, create_cart_for_user
from app.services.checkout import validate_checkout
from app.services.coupons import (
    apply_coupon_to_cart,
    calculate_coupon_discount,
    list_available_coupons,
    remove_coupon_from_cart,
)
from app.services.orders import create_order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com", phone="9000000000"):
    user = User(name="Customer", email=email, phone=phone, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, **overrides):
    owner = User(
        name="Owner",
        email=f"owner-{overrides.get('name', 'x')}@example.com",
        password_hash="x",
        role=UserRole.RESTAURANT_OWNER,
    )
    db.add(owner)
    db.commit()
    payload = {
        "owner_id": owner.id,
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("12.1"),
        "longitude": Decimal("77.1"),
        "minimum_order": Decimal("0.00"),
        "delivery_fee": Decimal("30.00"),
        "is_active": True,
        "is_open": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    return restaurant


def _address(db, user):
    from app.models import Address

    address = Address(
        user_id=user.id,
        label="Home",
        recipient_name="Customer",
        phone="9999999999",
        address_line="15 Market Road",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560001",
        is_default=True,
    )
    db.add(address)
    db.commit()
    return address


def _coupon(db, **overrides):
    payload = {
        "code": "SAVE10",
        "discount_type": DiscountType.PERCENT,
        "discount_value": Decimal("10"),
        "min_order": Decimal("0.00"),
        "is_active": True,
    }
    payload.update(overrides)
    coupon = Coupon(**payload)
    db.add(coupon)
    db.commit()
    return coupon


def _cart_with_item(db, user, restaurant, price=Decimal("200.00")):
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    return cart


def test_discount_calculation_percent_and_fixed_with_max_cap(db):
    percent = _coupon(db, code="P10", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"), max_discount=Decimal("15.00"))
    assert calculate_coupon_discount(percent, Decimal("200.00")) == Decimal("15.00")  # 20 capped to 15

    fixed = _coupon(db, code="F50", discount_type=DiscountType.FIXED, discount_value=Decimal("50.00"))
    assert calculate_coupon_discount(fixed, Decimal("200.00")) == Decimal("50.00")

    fixed_capped_by_total = _coupon(db, code="F500", discount_type=DiscountType.FIXED, discount_value=Decimal("500.00"))
    assert calculate_coupon_discount(fixed_capped_by_total, Decimal("200.00")) == Decimal("200.00")


def test_apply_coupon_rejects_before_start_date(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant)
    coupon = _coupon(db, start_date=datetime.now(UTC) + timedelta(days=1))

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, coupon.code)
    assert "isn't active yet" in exc.value.detail


def test_apply_coupon_rejects_after_end_date(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant)
    coupon = _coupon(db, end_date=datetime.now(UTC) - timedelta(days=1))

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, coupon.code)
    assert "expired" in exc.value.detail


def test_apply_coupon_enforces_minimum_order(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant, price=Decimal("50.00"))
    coupon = _coupon(db, min_order=Decimal("100.00"))

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, coupon.code)
    assert "minimum order" in exc.value.detail


def test_apply_coupon_rejects_wrong_restaurant(db):
    user = _customer(db)
    restaurant = _restaurant(db, name="chai-house")
    other_restaurant = _restaurant(db, name="other")
    cart = _cart_with_item(db, user, restaurant)
    coupon = _coupon(db, restaurant_id=other_restaurant.id)

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, coupon.code)
    assert "isn't valid for this restaurant" in exc.value.detail


def test_apply_coupon_enforces_usage_limit(db):
    user = _customer(db)
    other_user = _customer(db, email="other@example.com", phone="9111111111")
    restaurant = _restaurant(db)
    coupon = _coupon(db, usage_limit=1, per_customer_limit=None)

    other_cart = _cart_with_item(db, other_user, restaurant)
    other_address = _address(db, other_user)
    apply_coupon_to_cart(db, other_user.id, other_cart, coupon.code)
    create_order(db, other_user, other_address.id)

    cart = _cart_with_item(db, user, restaurant)
    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, coupon.code)
    assert "usage limit" in exc.value.detail


def test_apply_coupon_enforces_per_customer_limit(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant)
    coupon = _coupon(db, per_customer_limit=1)

    address = _address(db, user)
    apply_coupon_to_cart(db, user.id, cart, coupon.code)
    order = create_order(db, user, address.id)
    assert order.discount == Decimal("20.00")

    redemption_count = db.query(CouponRedemption).filter(CouponRedemption.coupon_id == coupon.id).count()
    assert redemption_count == 1

    cart2 = create_cart_for_user(db, user.id)
    product2 = Product(restaurant_id=restaurant.id, name="Naan", price=Decimal("200.00"))
    db.add(product2)
    db.commit()
    add_item(db, cart2, product2.id, 1)

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart2, coupon.code)
    assert "maximum number of times" in exc.value.detail


def test_apply_and_remove_coupon_updates_cart_totals(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant)
    _coupon(db, code="SAVE10", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"))

    apply_coupon_to_cart(db, user.id, cart, "SAVE10")
    totals = calculate_cart_totals(db, cart)
    assert totals["discount"] == Decimal("20.00")
    assert totals["coupon_code"] == "SAVE10"
    assert totals["total"] == Decimal("200.00") + Decimal("30.00") - Decimal("20.00")

    remove_coupon_from_cart(db, cart)
    totals_after = calculate_cart_totals(db, cart)
    assert totals_after["discount"] == Decimal("0.00")
    assert totals_after["coupon_code"] is None


def test_cart_self_heals_when_coupon_becomes_invalid(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant, price=Decimal("150.00"))
    coupon = _coupon(db, min_order=Decimal("100.00"))

    apply_coupon_to_cart(db, user.id, cart, coupon.code)
    coupon.min_order = Decimal("1000.00")
    db.commit()

    totals = calculate_cart_totals(db, cart)
    assert totals["discount"] == Decimal("0.00")
    assert totals["coupon_code"] is None
    assert totals["coupon_message"] is not None
    assert "removed" in totals["coupon_message"]

    db.refresh(cart)
    assert cart.coupon_id is None


def test_invalid_coupon_code_rejected(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant)

    with pytest.raises(HTTPException) as exc:
        apply_coupon_to_cart(db, user.id, cart, "DOESNOTEXIST")
    assert exc.value.status_code == 404


def test_coupon_discount_flows_into_checkout_and_order(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    cart = _cart_with_item(db, user, restaurant, price=Decimal("200.00"))
    _coupon(db, code="SAVE10", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"))
    apply_coupon_to_cart(db, user.id, cart, "SAVE10")
    address = _address(db, user)

    validation = validate_checkout(db, user, address.id)
    assert validation["coupon_code"] == "SAVE10"
    assert validation["discount"] == Decimal("20.00")

    order = create_order(db, user, address.id)
    assert order.discount == Decimal("20.00")
    assert order.total == Decimal("200.00") + Decimal("30.00") - Decimal("20.00")

    redemption = db.query(CouponRedemption).filter(CouponRedemption.order_id == order.id).first()
    assert redemption is not None
    assert redemption.user_id == user.id


def test_list_available_coupons_excludes_inactive_and_expired(db):
    _coupon(db, code="ACTIVE1", is_active=True)
    _coupon(db, code="INACTIVE1", is_active=False)
    _coupon(db, code="EXPIRED1", end_date=datetime.now(UTC) - timedelta(days=1))
    _coupon(db, code="FUTURE1", start_date=datetime.now(UTC) + timedelta(days=1))

    available = list_available_coupons(db)
    codes = {c.code for c in available}
    assert codes == {"ACTIVE1"}
