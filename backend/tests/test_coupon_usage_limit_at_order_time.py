"""E2E Validation Phase 15 — a coupon's usage limits are re-checked under a
row lock when the order is actually created, not only when it was applied
to the cart. Reproduced on PostgreSQL: six customers ordering at once all
redeemed a usage_limit=1 coupon. (SQLite can't show the lock itself; this
proves the at-order-time re-check that the lock serialises.)"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Coupon, DiscountType
from app.models.coupon import CouponRedemption
from app.services.orders import _next_order_number, create_order
from tests.test_restaurant_portal_final_suite import _owner, _restaurant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_an_order_is_refused_when_the_coupon_ran_out_after_it_was_validated(db, monkeypatch):
    from app.models import Product, User, UserRole
    from app.services import orders as orders_module
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user

    restaurant = _restaurant(db, _owner(db))
    coupon = Coupon(code="ONLYONE", discount_type=DiscountType.FIXED, discount_value=Decimal("10.00"), usage_limit=1, per_customer_limit=1)
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add_all([coupon, product])
    db.commit()

    def shopper(tag):
        user = User(name=f"Buyer {tag}", email=f"buyer-{tag}@example.com", password_hash="x", role=UserRole.CUSTOMER)
        db.add(user)
        db.commit()
        cart = create_cart_for_user(db, user.id)
        add_item(db, cart, product.id, 1)
        cart.coupon_id = coupon.id
        db.commit()
        address = create_address(db, user.id, {"label": "Home", "recipient_name": f"Buyer {tag}", "phone": "9999999999",
                                               "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001"})
        return user, address

    buyer_a, address_a = shopper("a")
    buyer_b, address_b = shopper("b")

    # The race window: B's checkout is validated while the coupon is still free...
    stale_validation = orders_module.validate_checkout(db, buyer_b, address_b.id)
    assert stale_validation["coupon_id"] == coupon.id
    # ...then A's order uses up the single redemption...
    create_order(db, buyer_a, address_a.id)
    # ...and B's order proceeds on that stale validation.
    monkeypatch.setattr(orders_module, "validate_checkout", lambda *args, **kwargs: stale_validation)
    with pytest.raises(ValueError, match="usage limit"):
        create_order(db, buyer_b, address_b.id)

    assert db.query(CouponRedemption).count() == 1


def test_order_numbers_carry_ten_hex_digits():
    number = _next_order_number()
    prefix, date, suffix = number.split("-")
    assert prefix == "ORD" and len(date) == 8 and len(suffix) == 10 and len(number) <= 32
